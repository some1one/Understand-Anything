//! Filesystem adapters for deterministic batch pipeline commands.
use std::{
    env, fs,
    path::{Path, PathBuf},
};
use understand_anything::{
    self as ua, Error, Result,
    persistence::{read_json, write_json},
};
fn root(path: &str) -> Result<PathBuf> {
    let p = PathBuf::from(path);
    Ok(if p.is_absolute() {
        p
    } else {
        env::current_dir()?.join(p)
    })
}
pub fn run(command: &str, args: &[String]) -> Result<i32> {
    let count = match command {
        "seed_file_batch_graph" => 3,
        "finalize_file_batch_output" => 4,
        _ => 2,
    };
    if args.len() < count {
        return Err(Error::Invalid(format!(
            "Usage: understand-anything-rs {command}: expected at least {count} arguments"
        )));
    }
    match command {
        "seed_file_batch_graph" => {
            let extraction = read_json(Path::new(&args[1]))?;
            if !ua::array(&extraction, "filesUnreadable").is_empty() {
                return Err(Error::Invalid("Cannot seed a batch with unreadable source files; repair the extraction input first".into()));
            }
            let seed = ua::seed::build_seed(&read_json(Path::new(&args[0]))?, &extraction);
            let path = Path::new(&args[2]);
            write_json(path, &seed)?;
            let imports = ua::array(&seed, "edges")
                .iter()
                .filter(|e| e["type"] == "imports")
                .count();
            eprintln!(
                "seed_file_batch_graph: batch {} → {} nodes, {} edges ({imports} imports) written to {}",
                seed["batchIndex"],
                ua::array(&seed, "nodes").len(),
                ua::array(&seed, "edges").len(),
                path.display()
            );
        }
        "prepare_file_analysis_batch" => {
            let root = root(&args[0])?;
            let wanted = args[1..]
                .iter()
                .map(|s| {
                    s.parse::<i64>().map_err(|_| {
                        Error::Invalid(
                            "prepare_file_analysis_batch: batch indices must be integers".into(),
                        )
                    })
                })
                .collect::<Result<Vec<_>>>()?;
            let path = ua::persistence::data_dir(&root).join("intermediate/batches.json");
            let doc = read_json(&path)?;
            let by_index: std::collections::BTreeMap<_, _> = ua::array(&doc, "batches")
                .iter()
                .filter_map(|b| b["batchIndex"].as_i64().map(|i| (i, b)))
                .collect();
            let tmp = ua::persistence::data_dir(&root).join("tmp");
            fs::create_dir_all(&tmp)?;
            let mut written = 0;
            for idx in wanted {
                let batch=by_index.get(&idx).ok_or_else(||Error::Invalid(format!("prepare_file_analysis_batch failed: batch {idx} not found in {} (available: {:?})",path.display(),by_index.keys().collect::<Vec<_>>())))?;
                let (input, context) =
                    ua::seed::build_batch_payloads(&root.to_string_lossy(), batch);
                ua::schemas::validate("structure-input", &input)?;
                ua::schemas::validate("file-analysis-context", &context)?;
                write_json(
                    &tmp.join(format!("ua-file-analyzer-input-{idx}.json")),
                    &input,
                )?;
                write_json(&tmp.join(format!("ua-file-context-{idx}.json")), &context)?;
                written += 1;
                eprintln!(
                    "prepare_file_analysis_batch: batch {idx} → {} files, {} neighbor entries",
                    ua::array(&context, "batchFiles").len(),
                    context["neighborMap"]
                        .as_object()
                        .map(|o| o.len())
                        .unwrap_or(0)
                );
            }
            eprintln!("prepare_file_analysis_batch: prepared {written} batch(es)");
        }
        "validate_structure_output" => {
            let input = read_json(Path::new(&args[0]))?;
            let output = read_json(Path::new(&args[1]))?;
            let issues = ua::batch_validation::check_structure_output(&input, &output);
            if !issues.is_empty() {
                eprintln!(
                    "validate_structure_output: {} issue(s) found:",
                    issues.len()
                );
                for issue in issues {
                    eprintln!("  - {issue}");
                }
                return Ok(1);
            }
            eprintln!(
                "validate_structure_output: OK ({} files analyzed, {} skipped)",
                output["filesAnalyzed"],
                ua::array(&output, "filesSkipped").len()
            );
        }
        "validate_layers" => {
            if args.len() != 2 {
                return Err(Error::Invalid(
                    "validate_layers requires input.json and layers.json".into(),
                ));
            }
            let input = read_json(Path::new(&args[0]))?;
            let layers = read_json(Path::new(&args[1]))?;
            let issues = ua::batch_validation::check_layers(&input, &layers);
            if !issues.is_empty() {
                eprintln!("LAYER VALIDATION FAILED:");
                for issue in issues {
                    eprintln!("  - {issue}");
                }
                return Ok(1);
            }
            println!(
                "OK: {} layers, all {} input nodes assigned to exactly one layer.",
                layers.as_array().unwrap().len(),
                ua::array(&input, "fileNodes").len()
            );
        }
        "finalize_file_batch_output" => {
            let root = root(&args[0])?;
            let context = read_json(Path::new(&args[1]))?;
            let seed = read_json(Path::new(&args[2]))?;
            let draft = ua::batch_validation::graph_fragment(&read_json(Path::new(&args[3]))?);
            let issues = ua::batch_validation::validate_draft(&context, &seed, &draft);
            if !issues.is_empty() {
                eprintln!(
                    "finalize_file_batch_output: {} issue(s) — NOT writing batch files:",
                    issues.len()
                );
                for issue in issues {
                    eprintln!("  - {issue}");
                }
                return Ok(1);
            }
            let idx = context["batchIndex"].as_i64().ok_or_else(|| {
                Error::Invalid(
                    "finalize_file_batch_output failed: context has no integer batchIndex".into(),
                )
            })?;
            let files = ua::array(&context, "batchFiles")
                .iter()
                .filter_map(|f| f["path"].as_str().map(str::to_owned))
                .collect::<Vec<_>>();
            let out = ua::persistence::data_dir(&root).join("intermediate");
            fs::create_dir_all(&out)?;
            let fragments = ua::batch_validation::split_into_parts(
                ua::array(&draft, "nodes"),
                ua::array(&draft, "edges"),
                &files,
            );
            let written = ua::batch_files::replace(&out, idx, &fragments)?;
            eprintln!(
                "finalize_file_batch_output: batch {idx} OK — {} nodes, {} edges → {}",
                ua::array(&draft, "nodes").len(),
                ua::array(&draft, "edges").len(),
                written.join(", ")
            );
        }
        "assemble_part_graph" => {
            let root = root(&args[0])?;
            let part = &args[1];
            let commit = args.get(2).map(String::as_str).unwrap_or("");
            let inter = ua::persistence::data_dir(&root).join("intermediate");
            let scan = read_json(&inter.join("scan-result.json"))?;
            let assembled = read_json(&inter.join("assembled-graph.json"))?;
            let known = ua::array(&scan, "files")
                .iter()
                .filter_map(|f| {
                    f["path"]
                        .as_str()
                        .filter(|s| !s.is_empty())
                        .map(str::to_owned)
                })
                .collect();
            let mut graph = ua::assembly::build_part_graph(&assembled, part, &known, &scan, commit);
            let dir = ua::persistence::data_dir(&root).join("partitions");
            fs::create_dir_all(&dir)?;
            let path = dir.join(ua::partition::part_to_filename(part));
            let previous = if path.exists() { read_json(&path)? } else { serde_json::Value::Null };
            let preparation = ua::partition_updates::verify_preparation(&root,part,&previous)?;
            if !previous.is_null() {
                let report=ua::incremental_symbols::validate_part_replacement(&root, part, &previous, &graph, &scan)?;
                if let Some(preparation)=&preparation {
                    let candidates=read_json(&inter.join("part-edge-candidates.json"))?;
                    if candidates["version"]!=1 || candidates["preparation"]!=*preparation || candidates["graphHash"]!=ua::incremental_symbols::edge_candidate_hash(&assembled)? {
                        return Err(Error::Invalid("Partition edge evidence is stale; rerun batch merging".into()));
                    }
                    let selected=ua::strings(&preparation["plan"]["filesToAnalyze"]).into_iter().collect();
                    let retry=ua::partition_updates::retry_state(&root,part,preparation)?;
                    if retry.as_ref().is_some_and(|r|r["status"]!="ready") { return Err(Error::Invalid("Partition repair preparation is incomplete; preserve recovery evidence".into())); }
                    ua::incremental_symbols::restore_part_edges(&previous,&mut graph,&report,&selected,&candidates,retry.as_ref())?;
                }
            } else if !ua::array(&scan, "failures").is_empty() {
                return Err(Error::Invalid("Cannot publish a partition from an incomplete scan".into()));
            }
            if let Some(preparation)=&preparation {
                graph = ua::updates::refresh_graph_imports(&graph,&preparation["scan"]["importMap"],&ua::strings(&preparation["plan"]["assignedFiles"]))?;
                ua::updates::validate_analyzed_file_coverage(ua::array(&graph,"nodes"),&ua::strings(&preparation["plan"]["assignedFiles"]))?;
            }
            write_json(&path, &graph)?;
            for entry in fs::read_dir(&inter)? {
                let entry = entry?;
                let name = entry.file_name().to_string_lossy().into_owned();
                if (name.starts_with("batch-") && name.ends_with(".json"))
                    || ["assembled-graph.json", "part-update.json", "part-edge-candidates.json"].contains(&name.as_str())
                    || name == format!("part-symbol-retry-{}.json",part.replace('/',"~"))
                {
                    fs::remove_file(entry.path())?;
                }
            }
            let summary = serde_json::json!({"outputPath":path,"part":part,"nodes":ua::array(&graph,"nodes").len(),"edges":ua::array(&graph,"edges").len(),"boundaryStubs":ua::array(&graph,"nodes").iter().filter(|n|n["stub"]==true).count()});
            println!("{}", serde_json::to_string_pretty(&summary)?);
        }
        _ => {
            return Err(Error::Invalid(format!(
                "Unknown pipeline command {command}"
            )));
        }
    }
    Ok(0)
}
