mod helper_cli;
mod pipeline_cli;
use serde_json::json;
use std::{
    env, fs,
    path::{Path, PathBuf},
    process::ExitCode,
};
use understand_anything::{
    self as ua, Error, Result, partition,
    persistence::{read_json, write_json},
};
const IMPLEMENTED: &[&str] = &[
    "data_dir",
    "capture_project_context",
    "write_changed_files",
    "prune_incremental_batch",
    "save_knowledge_graph",
    "diff_context",
    "query_graph",
    "query_payload",
    "query_terms",
    "helper_request",
    "refresh_query_dictionaries",
    "merge_batch_graphs",
    "auto_update_preflight",
    "auto_update_fingerprint_check",
    "auto_update_prepare_batches",
    "auto_update_apply_batches",
    "auto_update_finalize",
    "extract_import_map",
    "extract_domain_context",
    "build_fingerprints",
    "extract_structure",
    "generate_input",
    "validate_graph",
    "validate_assembled_graph",
    "validate_domain_graph",
    "compute_batches",
    "seed_file_batch_graph",
    "prepare_file_analysis_batch",
    "validate_structure_output",
    "validate_layers",
    "finalize_file_batch_output",
    "assemble_part_graph",
    "analyze",
    "generate_ignore",
    "assemble_project_scan_result",
    "scan_project",
    "detect_layout",
    "partition_files",
    "affected_parts",
    "parts_to_process",
    "write_config",
    "json_schema",
    "merge_parts",
    "merge_subdomain_graphs",
];
fn usage(command: &str, syntax: &str) -> Error {
    Error::Invalid(format!("Usage: understand-anything-rs {command} {syntax}"))
}
fn require<'a>(
    args: &'a [String],
    count: usize,
    command: &str,
    syntax: &str,
) -> Result<&'a [String]> {
    if args.len() < count {
        Err(usage(command, syntax))
    } else {
        Ok(args)
    }
}
fn scan_paths(root: &Path) -> Result<Vec<String>> {
    let scan = read_json(&ua::persistence::data_dir(&root).join("intermediate/scan-result.json"))?;
    Ok(ua::array(&scan, "files")
        .iter()
        .filter_map(|f| {
            f["path"]
                .as_str()
                .filter(|p| !p.is_empty())
                .map(str::to_owned)
        })
        .collect())
}
fn changed(path: &Path) -> Result<Vec<String>> {
    let raw = fs::read_to_string(path)?;
    Ok(raw
        .split(if raw.contains('\0') { '\0' } else { '\n' })
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect())
}
fn absolute(p: &str) -> Result<PathBuf> {
    let p = PathBuf::from(p);
    Ok(if p.is_absolute() {
        p
    } else {
        env::current_dir()?.join(p)
    })
}
fn execute(mut args: Vec<String>) -> Result<i32> {
    let mut cache = None;
    let mut i = 0;
    while i < args.len() {
        if args[i] == "--parser-cache-dir" {
            if i + 1 >= args.len() {
                return Err(Error::Invalid(
                    "--parser-cache-dir requires a directory".into(),
                ));
            }
            cache = Some(PathBuf::from(args.remove(i + 1)));
            args.remove(i);
        } else if let Some(p) = args[i].strip_prefix("--parser-cache-dir=") {
            cache = Some(PathBuf::from(p));
            args.remove(i);
        } else {
            i += 1;
        }
    }
    ua::parsers::configure(cache.as_deref())?;
    if args.is_empty() || ["--help", "-h"].contains(&args[0].as_str()) {
        println!(
            "understand-anything-rs — native engine port\n\nImplemented commands:\n  {}\n  parsers list | fetch [languages…]\n\nGlobal option: --parser-cache-dir PATH\nSee reference/coverage.json for parity status.",
            IMPLEMENTED.join("\n  ")
        );
        return Ok(0);
    }
    if args[0] == "--version" {
        println!("understand-anything-rs {}", env!("CARGO_PKG_VERSION"));
        return Ok(0);
    }
    let command = args.remove(0);
    let command = match command.as_str() {
        "scan" => "scan_project",
        "batches" => "compute_batches",
        "structure" => "extract_structure",
        "domain-context" => "extract_domain_context",
        "import-map" => "extract_import_map",
        "merge-batches" => "merge_batch_graphs",
        "auto-update-preflight" => "auto_update_preflight",
        "auto-update-fingerprint-check" => "auto_update_fingerprint_check",
        "auto-update-prepare-batches" => "auto_update_prepare_batches",
        "auto-update-apply-batches" => "auto_update_apply_batches",
        "auto-update-finalize" => "auto_update_finalize",
        "validate-graph" => "validate_graph",
        "validate-assembled-graph" => "validate_assembled_graph",
        "validate-domain-graph" => "validate_domain_graph",
        "seed-file-batch" => "seed_file_batch_graph",
        "prepare-batch" => "prepare_file_analysis_batch",
        "validate-structure-output" => "validate_structure_output",
        "finalize-file-batch" => "finalize_file_batch_output",
        "assemble-scan" => "assemble_project_scan_result",
        "merge-subdomains" => "merge_subdomain_graphs",
        s => s,
    };
    if helper_cli::COMMANDS.contains(&command) {
        return helper_cli::run(command, &args);
    }
    match command {
        "data_dir" => {
            require(&args, 1, command, "<project-root>")?;
            println!(
                "{}",
                ua::persistence::data_dir(&absolute(&args[0])?).display()
            );
        }
        "merge_batch_graphs" => {
            require(&args, 1, command, "<project-root>")?;
            ua::batch_merge::merge_batch_directory(&absolute(&args[0])?)?;
        }
        "auto_update_preflight"
        | "auto_update_fingerprint_check"
        | "auto_update_prepare_batches"
        | "auto_update_apply_batches"
        | "auto_update_finalize" => {
            let positional: Vec<_> = if command == "auto_update_preflight" {
                args.iter()
                    .filter(|s| !s.starts_with('-'))
                    .cloned()
                    .collect()
            } else {
                args.clone()
            };
            require(&positional, 1, command, "<project-root> [--force]")?;
            let output = ua::updates::run_command(
                command,
                &absolute(&positional[0])?,
                args.iter().any(|s| s == "--force"),
            )?;
            let raw = serde_json::to_string(&output)?;
            let (mut quoted, mut escaped) = (false, false);
            let mut text = String::new();
            for c in raw.chars() {
                text.push(c);
                if escaped {
                    escaped = false;
                } else if quoted && c == '\\' {
                    escaped = true;
                } else if c == '"' {
                    quoted = !quoted;
                } else if !quoted && [',', ':'].contains(&c) {
                    text.push(' ');
                }
            }
            println!("{text}");
        }
        "extract_import_map" => {
            require(&args, 2, command, "<input.json> <output.json>")?;
            let result = ua::imports::extract_import_map(&read_json(Path::new(&args[0]))?)?;
            write_json(Path::new(&args[1]), &result)?;
            eprintln!(
                "extract-import-map: filesScanned={} filesWithImports={} totalEdges={}",
                result["stats"]["filesScanned"],
                result["stats"]["filesWithImports"],
                result["stats"]["totalEdges"]
            );
        }
        "extract_domain_context" => {
            let mut positional = vec![];
            let mut output = None;
            let mut i = 0;
            while i < args.len() {
                if args[i] == "--output" && i + 1 < args.len() {
                    i += 1;
                    output = Some(PathBuf::from(&args[i]));
                } else if let Some(p) = args[i].strip_prefix("--output=") {
                    output = Some(PathBuf::from(p));
                } else {
                    positional.push(args[i].clone());
                }
                i += 1;
            }
            require(&positional, 1, command, "<project-root> [--output PATH]")?;
            let root = absolute(&positional[0])?;
            if !root.is_dir() {
                return Err(Error::Invalid(format!(
                    "Error: {} is not a directory",
                    root.display()
                )));
            }
            let output = output.unwrap_or_else(|| {
                ua::persistence::data_dir(&root).join("intermediate/domain-context.json")
            });
            if let Some(parent) = output.parent().filter(|p| !p.as_os_str().is_empty()) {
                fs::create_dir_all(parent)?;
            }
            eprintln!("Scanning {} ...", root.display());
            let context = ua::domain_context::extract(&root)?;
            eprintln!("  Found {} source files", context["fileCount"]);
            eprintln!(
                "  Detected {} entry points",
                ua::array(&context, "entryPoints").len()
            );
            eprintln!(
                "  Extracted {} file signatures",
                ua::array(&context, "fileSignatures").len()
            );
            eprintln!(
                "  Read {} metadata files",
                context["metadata"].as_object().unwrap().len()
            );
            let text = ua::domain_context::ascii_json(&context)?;
            fs::write(&output, &text)?;
            eprintln!(
                "  Wrote {} ({:.0} KB)",
                output.display(),
                (text.len() as f64 / 1024.).round_ties_even()
            );
        }
        "build_fingerprints" => {
            require(&args, 1, command, "<input.json>")?;
            let input = read_json(Path::new(&args[0]))?;
            if input["projectRoot"].as_str().is_none_or(str::is_empty)
                || !input["sourceFilePaths"].is_array()
                || !input["gitCommitHash"].is_string()
            {
                return Err(Error::Invalid("Invalid input: requires { projectRoot: str, sourceFilePaths: [str], gitCommitHash: str }".into()));
            }
            let root = Path::new(input["projectRoot"].as_str().unwrap());
            let store = ua::fingerprints::build_fingerprint_store(
                root,
                &ua::strings(&input["sourceFilePaths"]),
                input["gitCommitHash"].as_str().unwrap(),
            );
            let dir = ua::persistence::data_dir(&root);
            fs::create_dir_all(&dir)?;
            write_json(&dir.join("fingerprints.json"), &store)?;
            println!(
                "Fingerprints baseline: {} files",
                store["files"].as_object().unwrap().len()
            );
        }
        "extract_structure" => {
            require(&args, 2, command, "<input.json> <output.json>")?;
            let result = ua::structure::extract_structure(&read_json(Path::new(&args[0]))?)?;
            write_json(Path::new(&args[1]), &result)?;
        }
        "generate_input" => {
            let invalid = |message: &str| Error::Usage {
                status: 2,
                message: format!("understand-anything-rs generate_input: {message}"),
            };
            if args.iter().any(|a| a == "--help" || a == "-h") {
                println!(
                    "Usage: understand-anything-rs generate_input <project_root> <output> [--include GLOB ...] [--exclude GLOB ...] [--no-gitignore]"
                );
                return Ok(0);
            }
            let mut positional = vec![];
            let mut include = vec![];
            let mut exclude = vec![];
            let mut respect = true;
            let mut i = 0;
            while i < args.len() {
                let arg = &args[i];
                if arg == "--no-gitignore" {
                    respect = false;
                } else if arg == "--include"
                    || arg == "--exclude"
                    || arg.starts_with("--include=")
                    || arg.starts_with("--exclude=")
                {
                    let target = if arg.starts_with("--include") {
                        &mut include
                    } else {
                        &mut exclude
                    };
                    let before = target.len();
                    if let Some((_, value)) = arg.split_once('=') {
                        target.push(value.to_owned());
                    } else {
                        while i + 1 < args.len() && !args[i + 1].starts_with('-') {
                            i += 1;
                            target.push(args[i].clone());
                        }
                    }
                    if target.len() == before {
                        return Err(invalid(&format!(
                            "argument {arg}: expected at least one argument"
                        )));
                    }
                } else if arg.starts_with('-') {
                    return Err(invalid(&format!("unrecognized arguments: {arg}")));
                } else {
                    positional.push(arg.clone());
                }
                i += 1;
            }
            if positional.len() != 2 {
                return Err(invalid("expected project_root and output"));
            }
            let root = absolute(&positional[0])?;
            if !root.is_dir() {
                return Err(Error::Invalid(format!(
                    "understand_core.generate_input: NotADirectoryError: not a directory: {}",
                    root.display()
                )));
            }
            let result = ua::input::generate(&root, &include, &exclude, respect)?;
            let out = Path::new(&positional[1]);
            if let Some(parent) = out.parent().filter(|p| !p.as_os_str().is_empty()) {
                fs::create_dir_all(parent)?;
            }
            write_json(out, &result)?;
            println!(
                "wrote {} file nodes to {}",
                ua::array(&result, "fileNodes").len(),
                out.display()
            );
        }
        "validate_graph" | "validate_assembled_graph" | "validate_domain_graph" => {
            let mut positional = vec![];
            let mut scan = None;
            let mut i = 0;
            while i < args.len() {
                if args[i] == "--scan-result" && i + 1 < args.len() {
                    i += 1;
                    scan = Some(args[i].clone());
                } else if let Some(p) = args[i].strip_prefix("--scan-result=") {
                    scan = Some(p.into());
                } else {
                    positional.push(args[i].clone());
                }
                i += 1;
            }
            let domain = command == "validate_domain_graph";
            require(
                &positional,
                if domain { 1 } else { 2 },
                command,
                "<graph.json> [review.json] [--scan-result PATH]",
            )?;
            let input = Path::new(&positional[0]);
            let output = positional
                .get(1)
                .map(PathBuf::from)
                .unwrap_or_else(|| input.with_file_name("domain-review.json"));
            let graph = read_json(input)?;
            let mut review = if domain {
                ua::strict_validation::review_domain_graph(&graph)
            } else {
                ua::strict_validation::review_graph(&graph, command == "validate_graph")
            };
            if let Some(p) = scan {
                match read_json(Path::new(&p)) {
                    Ok(data) => ua::strict_validation::add_scan_coverage(
                        &mut review,
                        &graph,
                        &ua::array(&data, "files")
                            .iter()
                            .filter_map(|f| f["path"].as_str().map(str::to_owned))
                            .collect::<Vec<_>>(),
                    ),
                    Err(e) => eprintln!("{command}: scan-coverage skipped — cannot read {p}: {e}"),
                }
            }
            write_json(&output, &review)?;
            let (issues, warnings) = (
                ua::array(&review, "issues").len(),
                ua::array(&review, "warnings").len(),
            );
            if domain {
                eprintln!("{command}: {issues} issues, {warnings} warnings");
            } else {
                let note = if command == "validate_assembled_graph"
                    && review["stats"]["coverage"].is_object()
                {
                    format!(
                        ", {} scanned files with no node",
                        review["stats"]["coverage"]["missingFileNodes"]
                    )
                } else {
                    String::new()
                };
                eprintln!(
                    "{command}: {issues} issues, {warnings} warnings ({} nodes, {} edges{note})",
                    review["stats"]["totalNodes"], review["stats"]["totalEdges"]
                );
            }
        }
        "compute_batches" => {
            require(&args, 1, command, "<project-root> [--changed-files PATH]")?;
            let root = absolute(&args[0])?;
            let mut changed_files = None;
            let mut i = 1;
            while i < args.len() {
                if let Some(p) = args[i].strip_prefix("--changed-files=") {
                    changed_files = Some(changed(Path::new(p))?.into_iter().collect());
                } else if args[i] == "--changed-files" && i + 1 < args.len() {
                    i += 1;
                    changed_files = Some(changed(Path::new(&args[i]))?.into_iter().collect());
                }
                i += 1;
            }
            let inter = ua::persistence::data_dir(&root).join("intermediate");
            let result = ua::batching::compute_batches(
                &root,
                &read_json(&inter.join("scan-result.json"))?,
                changed_files.as_ref(),
            );
            let output = inter.join("batches.json");
            write_json(&output, &result)?;
            let sizes: Vec<_> = ua::array(&result, "batches")
                .iter()
                .map(|b| ua::array(b, "files").len())
                .collect();
            eprintln!(
                "Wrote {} batches (sizes: max={}, min={}) to {}",
                sizes.len(),
                sizes.iter().max().unwrap_or(&0),
                sizes.iter().min().unwrap_or(&0),
                output.display()
            );
        }
        "seed_file_batch_graph"
        | "prepare_file_analysis_batch"
        | "validate_structure_output"
        | "validate_layers"
        | "finalize_file_batch_output"
        | "assemble_part_graph" => return pipeline_cli::run(command, &args),
        "analyze" => {
            require(&args, 2, command, "<input.json> <results.json>")?;
            if args.len() != 2 {
                return Err(usage(command, "<input.json> <results.json>"));
            }
            let result = ua::analytics::analyze(&read_json(Path::new(&args[0]))?)?;
            let output = Path::new(&args[1]);
            if let Some(parent) = output.parent().filter(|p| !p.as_os_str().is_empty()) {
                fs::create_dir_all(parent)?;
            }
            write_json(output, &result)?;
        }
        "generate_ignore" => {
            let root = if args.is_empty() {
                env::current_dir()?
            } else {
                absolute(&args[0])?
            };
            let dir = ua::persistence::data_dir(&root);
            let output = dir.join(".understandignore");
            if output.exists() {
                eprintln!(
                    "generate-ignore: {} already exists — skipping",
                    output.display()
                );
            } else {
                fs::create_dir_all(&dir)?;
                fs::write(
                    &output,
                    ua::ignore_generator::generate_starter_ignore_file(&root),
                )?;
                eprintln!("generate-ignore: wrote {}", output.display());
            }
        }
        "assemble_project_scan_result" => {
            require(
                &args,
                2,
                command,
                "<project-root> <narrative.json> [--scan PATH] [--import-map PATH] [--output PATH]",
            )?;
            let root = absolute(&args[0])?;
            let dir = ua::persistence::data_dir(&root);
            let mut scan = dir.join("tmp/ua-scan-files.json");
            let mut imports = dir.join("tmp/ua-import-map-output.json");
            let mut output = dir.join("intermediate/scan-result.json");
            let mut i = 2;
            while i < args.len() {
                if i + 1 >= args.len() {
                    return Err(Error::Invalid(format!(
                        "assemble_project_scan_result: unknown argument '{}'",
                        args[i]
                    )));
                }
                let target = match args[i].as_str() {
                    "--scan" => &mut scan,
                    "--import-map" => &mut imports,
                    "--output" => &mut output,
                    _ => {
                        return Err(Error::Invalid(format!(
                            "assemble_project_scan_result: unknown argument '{}'",
                            args[i]
                        )));
                    }
                };
                *target = PathBuf::from(&args[i + 1]);
                i += 2;
            }
            let result = ua::assembly::assemble_scan_result(
                &read_json(&scan)?,
                &read_json(&imports)?,
                &read_json(Path::new(&args[1]))?,
                &root,
            )?;
            ua::schemas::validate("project-scan-output", &result)?;
            if let Some(parent) = output.parent().filter(|p| !p.as_os_str().is_empty()) {
                fs::create_dir_all(parent)?;
            }
            write_json(&output, &result)?;
            eprintln!(
                "assemble_project_scan_result: wrote {} files, {} importMap entries to {}",
                result["totalFiles"],
                result["importMap"].as_object().unwrap().len(),
                output.display()
            );
        }
        "parsers" => {
            require(&args, 1, command, "list | fetch [languages…]")?;
            match args[0].as_str() {
                "list" => {
                    for lang in ua::parsers::LANGUAGES {
                        println!("{lang}");
                    }
                }
                "fetch" => ua::parsers::fetch(&args[1..])?,
                _ => return Err(usage(command, "list | fetch [languages…]")),
            }
        }
        "json_schema" => {
            let output = if args.is_empty() {
                PathBuf::from("./schemas")
            } else if args.len() == 2 && args[0] == "--output-dir" {
                PathBuf::from(&args[1])
            } else if args.len() == 1 && args[0].starts_with("--output-dir=") {
                PathBuf::from(&args[0][13..])
            } else {
                return Err(usage(command, "[--output-dir PATH]"));
            };
            for p in ua::schemas::export(&output)? {
                println!("wrote {}", p.display());
            }
        }
        "scan_project" => {
            require(&args, 2, command, "<projectRoot> <outputPath>")?;
            let root = Path::new(&args[0]);
            if !root.is_dir() {
                return Err(Error::Invalid(format!(
                    "scan_project failed: projectRoot {}: {}",
                    if root.exists() {
                        "is not a directory"
                    } else {
                        "does not exist"
                    },
                    root.display()
                )));
            }
            let result = ua::scan::scan_project(root)?;
            write_json(Path::new(&args[1]), &result)?;
            eprintln!(
                "scan-project: filesScanned={} filteredByIgnore={} complexity={}",
                result["totalFiles"],
                result["filteredByIgnore"],
                result["estimatedComplexity"].as_str().unwrap()
            );
        }
        "detect_layout" => {
            require(&args, 1, command, "<project-root>")?;
            println!(
                "{}",
                serde_json::to_string_pretty(&partition::detect_layout(&scan_paths(&absolute(
                    &args[0]
                )?)?))?
            );
        }
        "partition_files" => {
            require(
                &args,
                1,
                command,
                "<project-root> [--source=a,b] [--depth=N]",
            )?;
            let root = absolute(&args[0])?;
            let mut sources = vec![];
            let mut depth = None;
            for arg in &args[1..] {
                if let Some(raw) = arg.strip_prefix("--source=") {
                    sources = raw
                        .split(',')
                        .filter(|s| !s.trim().is_empty())
                        .map(str::to_owned)
                        .collect();
                } else if let Some(raw) = arg.strip_prefix("--depth=") {
                    depth = Some(
                        raw.parse::<usize>()
                            .map_err(|e| Error::Invalid(e.to_string()))?,
                    );
                }
            }
            let paths = scan_paths(&root)?;
            let mut parts = partition::partition_files(&paths, &sources, depth)?;
            // Retain included parts as empty work items so deletion updates can
            // replace their saved graphs through the normal assembly pipeline.
            for part in ua::strings(&ua::persistence::load_config(&root)["includedParts"]) {
                parts.entry(part).or_default();
            }
            let counts: serde_json::Map<_, _> = parts
                .iter()
                .map(|(k, v)| (k.clone(), json!(v.len())))
                .collect();
            let inter = ua::persistence::data_dir(&root).join("intermediate");
            fs::create_dir_all(&inter)?;
            write_json(
                &inter.join("partitions.json"),
                &json!({"parts":parts,"counts":counts}),
            )?;
            let lists = inter.join("part-files");
            fs::create_dir_all(&lists)?;
            for entry in fs::read_dir(&lists)? {
                let p = entry?.path();
                if p.extension().is_some_and(|s| s == "txt") {
                    fs::remove_file(p)?;
                }
            }
            for (name, files) in &parts {
                fs::write(
                    lists.join(format!("{}.txt", name.replace('/', "~"))),
                    format!("{}\n", files.join("\n")),
                )?;
            }
            eprintln!(
                "Partitioned {} files into {} parts:",
                paths.len(),
                parts.len()
            );
            for (name, files) in &parts {
                eprintln!("  {:>5}  {name}", files.len());
            }
        }
        "affected_parts" => {
            require(&args, 2, command, "<project-root> <changed-files.txt>")?;
            let root = absolute(&args[0])?;
            let config = ua::persistence::load_config(&root);
            for name in partition::affected_parts(
                &changed(Path::new(&args[1]))?,
                &ua::strings(&config["sourceFolders"]),
                config["splitDepth"].as_u64().map(|n| n as usize),
                &ua::strings(&config["includedParts"]),
            )? {
                println!("{name}");
            }
        }
        "parts_to_process" => {
            require(
                &args,
                1,
                command,
                "<project-root> [--full] [--changed=<file>]",
            )?;
            let mut paths = vec![];
            for arg in &args[1..] {
                if let Some(path) = arg.strip_prefix("--changed=")
                    && Path::new(path).exists()
                {
                    paths = changed(Path::new(path))?;
                }
            }
            for name in partition::parts_to_process(
                &absolute(&args[0])?,
                args.iter().any(|s| s == "--full"),
                &paths,
            )? {
                println!("{name}");
            }
        }
        "write_config" => {
            require(
                &args,
                1,
                command,
                "<project-root> [--source=a,b] [--depth=N] [--parts=x,y] [--auto-update=true|false]",
            )?;
            let root = absolute(&args[0])?;
            let config =
                partition::apply_updates(&ua::persistence::load_config(&root), &args[1..])?;
            if ua::strings(&config["sourceFolders"]).is_empty()
                && config["splitDepth"].as_i64().is_none_or(|n| n < 1)
            {
                return Err(Error::Invalid(
                    "Error: at least one of sourceFolders / splitDepth must be set.".into(),
                ));
            }
            ua::persistence::save_config(&root, &config)?;
            println!("{}", serde_json::to_string_pretty(&config)?);
        }
        "merge_parts" | "merge_subdomain_graphs" => {
            require(&args, 1, command, "<project-root> [files…]")?;
            let root = absolute(&args[0])?;
            let dir = ua::persistence::data_dir(&root);
            let is_parts = command == "merge_parts";
            if !is_parts && !dir.is_dir() {
                return Err(Error::Invalid(format!(
                    "Error: {} does not exist",
                    dir.display()
                )));
            }
            let files = if !is_parts && args.len() > 1 {
                args[1..]
                    .iter()
                    .map(|p| absolute(p))
                    .collect::<Result<Vec<_>>>()?
            } else {
                ua::merge::select_partition_graphs(&root)
            };
            if files.is_empty() {
                if is_parts {
                    return Err(Error::Invalid("No partition graphs found to merge".into()));
                }
                eprintln!("No subdomain graphs found to merge");
                return Ok(0);
            }
            if !is_parts {
                eprintln!("Found {} subdomain graphs:", files.len());
                for p in &files {
                    eprintln!(
                        "  - {}",
                        p.file_name().unwrap_or_default().to_string_lossy()
                    );
                }
            }
            let mut graphs = vec![];
            for p in &files {
                match ua::merge::load_graph(p) {
                    Ok(g) => {
                        if !is_parts {
                            eprintln!(
                                "    Loaded {}: {} nodes, {} edges",
                                p.file_name().unwrap_or_default().to_string_lossy(),
                                ua::array(&g, "nodes").len(),
                                ua::array(&g, "edges").len()
                            );
                        }
                        graphs.push(g);
                    }
                    Err(e) => eprintln!(
                        "  Skipping {}: {e}",
                        p.file_name().unwrap_or_default().to_string_lossy()
                    ),
                }
            }
            if graphs.is_empty() {
                return Err(Error::Invalid(format!(
                    "Error: no valid {} graphs loaded",
                    if is_parts { "partition" } else { "subdomain" }
                )));
            }
            let output = if is_parts {
                dir.join("intermediate/assembled-graph.json")
            } else {
                dir.join("knowledge-graph.json")
            };
            if !is_parts
                && output.exists()
                && let Ok(base) = ua::merge::load_graph(&output)
            {
                eprintln!(
                    "    Loaded base knowledge-graph.json: {} nodes, {} edges",
                    ua::array(&base, "nodes").len(),
                    ua::array(&base, "edges").len()
                );
                graphs.insert(0, base);
            }
            let (merged, report) = ua::merge::merge_graphs(&graphs);
            fs::create_dir_all(output.parent().unwrap())?;
            write_json(&output, &merged)?;
            if !is_parts {
                ua::query_dictionary::refresh(&output)?;
            }
            if !is_parts {
                eprintln!();
            }
            for line in report {
                eprintln!("{line}");
            }
            if is_parts {
                eprintln!("\nMerged {} parts → {}", graphs.len(), output.display());
            } else {
                eprintln!(
                    "\nWritten to {} ({:.0} KB)",
                    output.display(),
                    (fs::metadata(&output)?.len() as f64 / 1024.0).round_ties_even()
                );
                if ua::embeddings::embeddings_enabled() {
                    match ua::embeddings::generate_and_save(
                        &root,
                        ua::array(&merged, "nodes"),
                        None,
                        None,
                    ) {
                        Ok(p) => eprintln!("Wrote embeddings to {}", p.display()),
                        Err(e) => eprintln!("Embedding generation skipped: {e}"),
                    }
                }
            }
        }
        _ => {
            return Err(Error::Invalid(format!("Unknown command: {command}")));
        }
    }
    Ok(0)
}
fn main() -> ExitCode {
    match execute(env::args().skip(1).collect()) {
        Ok(code) => ExitCode::from(code as u8),
        Err(e) => {
            eprintln!("{e}");
            ExitCode::from(match e {
                Error::Usage { status, .. } => status,
                _ => 1,
            })
        }
    }
}
