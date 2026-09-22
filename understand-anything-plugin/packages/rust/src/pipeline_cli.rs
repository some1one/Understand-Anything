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
            let seed = ua::seed::build_seed(
                &read_json(Path::new(&args[0]))?,
                &read_json(Path::new(&args[1]))?,
            );
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
            let path = root.join(".understand-anything/intermediate/batches.json");
            let doc = read_json(&path)?;
            let by_index: std::collections::BTreeMap<_, _> = ua::array(&doc, "batches")
                .iter()
                .filter_map(|b| b["batchIndex"].as_i64().map(|i| (i, b)))
                .collect();
            let tmp = root.join(".understand-anything/tmp");
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
            let out = root.join(".understand-anything/intermediate");
            fs::create_dir_all(&out)?;
            let fragments = ua::batch_validation::split_into_parts(
                ua::array(&draft, "nodes"),
                ua::array(&draft, "edges"),
                &files,
            );
            let mut written = vec![];
            for (i, fragment) in fragments.iter().enumerate() {
                let name = if fragments.len() == 1 {
                    format!("batch-{idx}.json")
                } else {
                    format!("batch-{idx}-part-{}.json", i + 1)
                };
                write_json(&out.join(&name), fragment)?;
                written.push(name);
            }
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
            let inter = root.join(".understand-anything/intermediate");
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
            let graph = ua::assembly::build_part_graph(&assembled, part, &known, &scan, commit);
            let dir = root.join(".understand-anything/partitions");
            fs::create_dir_all(&dir)?;
            let path = dir.join(ua::partition::part_to_filename(part));
            write_json(&path, &graph)?;
            for entry in fs::read_dir(&inter)? {
                let entry = entry?;
                let name = entry.file_name().to_string_lossy().into_owned();
                if (name.starts_with("batch-") && name.ends_with(".json"))
                    || name == "assembled-graph.json"
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
