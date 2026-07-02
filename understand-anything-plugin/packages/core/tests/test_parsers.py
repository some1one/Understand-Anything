"""Port of parsers.test.ts."""

from __future__ import annotations

from understand_core.plugins.parsers import (
    DockerfileParser,
    EnvParser,
    GraphQLParser,
    JSONConfigParser,
    MakefileParser,
    MarkdownParser,
    ProtobufParser,
    SQLParser,
    ShellParser,
    TOMLParser,
    TerraformParser,
    YAMLConfigParser,
    strip_jsonc_syntax,
)


# --- MarkdownParser ---------------------------------------------------------

class TestMarkdownParser:
    parser = MarkdownParser()

    def test_extracts_heading_sections(self):
        content = "# Title\n\nIntro\n\n## Section A\n\nContent A\n\n### Subsection\n\nContent B"
        result = self.parser.analyze_file("README.md", content)
        assert len(result.sections) == 3
        assert result.sections[0]["name"] == "Title" and result.sections[0]["level"] == 1
        assert result.sections[1]["name"] == "Section A" and result.sections[1]["level"] == 2
        assert result.sections[2]["name"] == "Subsection" and result.sections[2]["level"] == 3

    def test_front_matter_not_imports(self):
        content = "---\ntitle: Test\ntags: [a, b]\n---\n# Content"
        result = self.parser.analyze_file("post.md", content)
        assert len(result.imports) == 0

    def test_extracts_file_references(self):
        content = "See [guide](./docs/guide.md) and ![img](./assets/logo.png)"
        refs = self.parser.extract_references("README.md", content)
        assert len(refs) == 2
        assert refs[0]["target"] == "./docs/guide.md" and refs[0]["referenceType"] == "file"
        assert refs[1]["target"] == "./assets/logo.png" and refs[1]["referenceType"] == "image"

    def test_skips_external_urls(self):
        content = "[link](https://example.com) and [local](./file.md)"
        refs = self.parser.extract_references("README.md", content)
        assert len(refs) == 1
        assert refs[0]["target"] == "./file.md"

    def test_empty_content(self):
        result = self.parser.analyze_file("empty.md", "")
        assert len(result.sections) == 0

    def test_ignores_headings_in_fenced_code(self):
        content = "\n".join(
            ["# Real Title", "", "Some intro.", "", "```bash", "# install", "npm install", "# build", "npm run build", "```", "", "## Real Section"]
        )
        result = self.parser.analyze_file("README.md", content)
        assert [s["name"] for s in result.sections] == ["Real Title", "Real Section"]

    def test_reenters_heading_detection_after_fence(self):
        content = "\n".join(["```", "# fake", "```", "# After fence"])
        result = self.parser.analyze_file("doc.md", content)
        assert [s["name"] for s in result.sections] == ["After fence"]


# --- YAMLConfigParser -------------------------------------------------------

class TestYAMLConfigParser:
    parser = YAMLConfigParser()

    def test_extracts_top_level_keys(self):
        content = "name: my-app\nversion: 1.0\nservices:\n  web:\n    image: node\n  db:\n    image: postgres"
        result = self.parser.analyze_file("config.yaml", content)
        assert result.sections is not None
        assert len(result.sections) >= 3
        names = [s["name"] for s in result.sections]
        assert "name" in names and "services" in names

    def test_handles_invalid_yaml(self):
        content = "invalid: yaml: content: [[["
        result = self.parser.analyze_file("broken.yaml", content)
        assert result.sections is not None

    def test_declares_yaml_flavored_formats(self):
        for lang in ["yaml", "kubernetes", "docker-compose", "github-actions", "openapi"]:
            assert lang in self.parser.languages

    def test_recognizes_quoted_top_level_keys(self):
        content = '"on":\n  push:\n    branches: [main]\nname: ci\n'
        result = self.parser.analyze_file(".github/workflows/ci.yml", content)
        names = [s["name"] for s in result.sections]
        assert "on" in names and "name" in names

    def test_array_root_one_section_per_entry(self):
        content = "- name: alpha\n  port: 80\n- name: beta\n  port: 443\n"
        result = self.parser.analyze_file("list.yaml", content)
        assert [s["name"] for s in result.sections] == ["alpha", "beta"]


# --- JSONConfigParser -------------------------------------------------------

class TestJSONConfigParser:
    parser = JSONConfigParser()

    def test_extracts_top_level_keys(self):
        content = '{\n  "name": "my-app",\n  "version": "1.0",\n  "dependencies": {}\n}'
        result = self.parser.analyze_file("package.json", content)
        names = [s["name"] for s in result.sections]
        assert "name" in names and "dependencies" in names

    def test_extracts_ref_references(self):
        content = '{\n  "$ref": "./common.json#/defs/User"\n}'
        refs = self.parser.extract_references("schema.json", content)
        assert len(refs) == 1
        assert refs[0]["target"] == "./common.json#/defs/User" and refs[0]["referenceType"] == "schema"

    def test_skips_internal_refs(self):
        content = '{\n  "$ref": "#/definitions/User"\n}'
        refs = self.parser.extract_references("schema.json", content)
        assert len(refs) == 0

    def test_handles_invalid_json(self):
        result = self.parser.analyze_file("broken.json", "not json at all")
        assert len(result.sections) == 0

    def test_declares_languages(self):
        assert self.parser.languages == ["json", "jsonc", "json-schema", "openapi"]

    def test_parses_jsonc_with_comments(self):
        content = "\n".join(
            ["{", "  // top-level comment", '  "name": "wrangler",', "  /* block", "     comment */", '  "main": "src/index.ts",', '  "compatibility_date": "2024-01-01",', "}"]
        )
        result = self.parser.analyze_file("wrangler.jsonc", content)
        assert [s["name"] for s in result.sections] == ["name", "main", "compatibility_date"]

    def test_preserves_comment_like_in_strings(self):
        content = '{\n  "url": "https://example.com//path",\n  "note": "/* not a comment */"\n}'
        result = self.parser.analyze_file("config.jsonc", content)
        assert [s["name"] for s in result.sections] == ["url", "note"]


class TestStripJsoncSyntax:
    def test_strips_line_comments(self):
        assert strip_jsonc_syntax('{"a": 1} // tail') == '{"a": 1} '

    def test_strips_block_comments(self):
        assert strip_jsonc_syntax('{/* x */ "a": 1}') == '{ "a": 1}'

    def test_strips_trailing_commas(self):
        assert strip_jsonc_syntax('{"a": 1,}') == '{"a": 1}'
        assert strip_jsonc_syntax('[1, 2,]') == '[1, 2]'

    def test_does_not_strip_slashes_in_strings(self):
        assert strip_jsonc_syntax('{"u": "http://x"}') == '{"u": "http://x"}'

    def test_handles_escaped_quotes(self):
        assert strip_jsonc_syntax('{"q": "say \\"hi\\""}') == '{"q": "say \\"hi\\""}'

    def test_leaves_plain_json_unchanged(self):
        plain = '{"a": 1, "b": [2, 3]}'
        assert strip_jsonc_syntax(plain) == plain


# --- TOMLParser -------------------------------------------------------------

class TestTOMLParser:
    parser = TOMLParser()

    def test_extracts_section_headers(self):
        content = '[package]\nname = "my-app"\n\n[dependencies]\nfoo = "1.0"\n\n[[bin]]\nname = "cli"'
        result = self.parser.analyze_file("Cargo.toml", content)
        assert len(result.sections) == 3
        assert result.sections[0]["name"] == "package"
        assert result.sections[1]["name"] == "dependencies"
        assert result.sections[2]["name"] == "[[bin]]"

    def test_empty_string(self):
        result = self.parser.analyze_file("empty.toml", "")
        assert result.sections is not None and len(result.sections) == 0

    def test_garbage_text(self):
        result = self.parser.analyze_file("garbage.toml", "this is not toml at all\nrandom garbage 123")
        assert result.sections is not None and len(result.sections) == 0


# --- EnvParser --------------------------------------------------------------

class TestEnvParser:
    parser = EnvParser()

    def test_extracts_variable_names(self):
        content = "# Database config\nDB_HOST=localhost\nDB_PORT=5432\n\n# API\nAPI_KEY=secret123"
        result = self.parser.analyze_file(".env", content)
        assert len(result.definitions) == 3
        assert [d["name"] for d in result.definitions] == ["DB_HOST", "DB_PORT", "API_KEY"]

    def test_skips_comments_and_empty(self):
        result = self.parser.analyze_file(".env", "# comment\n\nVAR=value")
        assert len(result.definitions) == 1

    def test_does_not_handle_export(self):
        result = self.parser.analyze_file(".env", "export DB_HOST=localhost\nAPI_KEY=secret")
        names = [d["name"] for d in result.definitions]
        assert "API_KEY" in names and "DB_HOST" not in names


# --- DockerfileParser -------------------------------------------------------

class TestDockerfileParser:
    parser = DockerfileParser()

    def test_extracts_from_stages(self):
        content = "FROM node:22-slim AS builder\nRUN npm install\n\nFROM node:22-slim AS runner\nCOPY --from=builder /app /app\nEXPOSE 3000"
        result = self.parser.analyze_file("Dockerfile", content)
        assert len(result.services) == 2
        assert result.services[0]["name"] == "builder" and result.services[0]["image"] == "node:22-slim"
        assert result.services[1]["name"] == "runner" and result.services[1]["image"] == "node:22-slim"

    def test_extracts_expose_ports(self):
        content = 'FROM node:22\nEXPOSE 3000 8080\nCMD ["node", "server.js"]'
        result = self.parser.analyze_file("Dockerfile", content)
        assert 3000 in result.services[0]["ports"]
        assert 8080 in result.services[0]["ports"]

    def test_extracts_steps(self):
        content = 'FROM node:22\nWORKDIR /app\nCOPY . .\nRUN npm install\nCMD ["node", "start"]'
        result = self.parser.analyze_file("Dockerfile", content)
        assert len(result.steps) == 5

    def test_expose_ports_correct_stage(self):
        content = 'FROM node:22 AS builder\nRUN npm install\n\nFROM node:22-slim AS runner\nCOPY --from=builder /app /app\nEXPOSE 3000 8080\nCMD ["node", "server.js"]'
        result = self.parser.analyze_file("Dockerfile", content)
        assert len(result.services) == 2
        assert len(result.services[0]["ports"]) == 0
        assert 3000 in result.services[1]["ports"]
        assert 8080 in result.services[1]["ports"]

    def test_line_range_per_stage(self):
        content = 'FROM node:22 AS builder\nRUN npm install\n\nFROM node:22-slim AS runner\nCOPY . .\nCMD ["node", "start"]'
        result = self.parser.analyze_file("Dockerfile", content)
        assert len(result.services) == 2
        assert result.services[0]["lineRange"][0] == 1
        assert result.services[1]["lineRange"][0] == 4


# --- SQLParser --------------------------------------------------------------

class TestSQLParser:
    parser = SQLParser()

    def test_extracts_create_table(self):
        content = (
            "CREATE TABLE users (\n  id INTEGER PRIMARY KEY,\n  name TEXT NOT NULL,\n  email TEXT UNIQUE\n);\n\n"
            "CREATE TABLE posts (\n  id INTEGER PRIMARY KEY,\n  user_id INTEGER,\n  title TEXT,\n  FOREIGN KEY (user_id) REFERENCES users(id)\n);"
        )
        result = self.parser.analyze_file("schema.sql", content)
        assert len(result.definitions) == 2
        assert result.definitions[0]["name"] == "users" and result.definitions[0]["kind"] == "table"
        for col in ("id", "name", "email"):
            assert col in result.definitions[0]["fields"]
        assert result.definitions[1]["name"] == "posts" and result.definitions[1]["kind"] == "table"

    def test_extracts_create_view(self):
        content = "CREATE VIEW active_users AS SELECT * FROM users WHERE active = true;"
        result = self.parser.analyze_file("views.sql", content)
        assert any(d["name"] == "active_users" and d["kind"] == "view" for d in result.definitions)

    def test_extracts_create_index(self):
        content = "CREATE UNIQUE INDEX idx_users_email ON users(email);"
        result = self.parser.analyze_file("indexes.sql", content)
        assert any(d["name"] == "idx_users_email" and d["kind"] == "index" for d in result.definitions)

    def test_create_table_if_not_exists(self):
        content = "CREATE TABLE IF NOT EXISTS users (id INT);"
        result = self.parser.analyze_file("schema.sql", content)
        assert len(result.definitions) == 1
        assert result.definitions[0]["name"] == "users" and result.definitions[0]["kind"] == "table"
        assert "id" in result.definitions[0]["fields"]

    def test_create_or_replace_view(self):
        content = "CREATE OR REPLACE VIEW active AS SELECT * FROM users;"
        result = self.parser.analyze_file("views.sql", content)
        assert any(d["name"] == "active" and d["kind"] == "view" for d in result.definitions)


# --- GraphQLParser ----------------------------------------------------------

class TestGraphQLParser:
    parser = GraphQLParser()

    def test_extracts_type_definitions(self):
        content = (
            "type User {\n  id: ID!\n  name: String!\n  email: String!\n}\n\n"
            "type Post {\n  id: ID!\n  title: String!\n  author: User!\n}"
        )
        result = self.parser.analyze_file("schema.graphql", content)
        assert len(result.definitions) == 2
        assert result.definitions[0]["name"] == "User" and result.definitions[0]["kind"] == "type"
        assert "id" in result.definitions[0]["fields"] and "name" in result.definitions[0]["fields"]
        assert result.definitions[1]["name"] == "Post"

    def test_extracts_query_mutation_endpoints(self):
        content = (
            "type Query {\n  users: [User!]!\n  user(id: ID!): User\n}\n\n"
            "type Mutation {\n  createUser(name: String!): User!\n}"
        )
        result = self.parser.analyze_file("schema.graphql", content)
        assert len(result.endpoints) >= 3
        assert any(e["method"] == "Query" and e["path"] == "users" for e in result.endpoints)
        assert any(e["method"] == "Mutation" and e["path"] == "createUser" for e in result.endpoints)

    def test_extracts_enum_definitions(self):
        content = "enum Role {\n  ADMIN\n  USER\n  GUEST\n}"
        result = self.parser.analyze_file("schema.graphql", content)
        assert any(d["name"] == "Role" and d["kind"] == "enum" for d in result.definitions)

    def test_extracts_input_type(self):
        content = "input CreateUserInput {\n  name: String!\n  email: String!\n}"
        result = self.parser.analyze_file("schema.graphql", content)
        input_def = next(d for d in result.definitions if d["name"] == "CreateUserInput")
        assert input_def["kind"] == "input"
        assert "name" in input_def["fields"]


# --- ProtobufParser ---------------------------------------------------------

class TestProtobufParser:
    parser = ProtobufParser()

    def test_extracts_message_definitions(self):
        content = "message User {\n  string name = 1;\n  int32 age = 2;\n  repeated string emails = 3;\n}"
        result = self.parser.analyze_file("user.proto", content)
        assert len(result.definitions) == 1
        assert result.definitions[0]["name"] == "User" and result.definitions[0]["kind"] == "message"
        for f in ("name", "age", "emails"):
            assert f in result.definitions[0]["fields"]

    def test_extracts_enum_definitions(self):
        content = "enum Status {\n  UNKNOWN = 0;\n  ACTIVE = 1;\n  INACTIVE = 2;\n}"
        result = self.parser.analyze_file("status.proto", content)
        assert any(d["name"] == "Status" and d["kind"] == "enum" for d in result.definitions)
        assert "UNKNOWN" in result.definitions[0]["fields"]
        assert "ACTIVE" in result.definitions[0]["fields"]

    def test_extracts_service_rpc_methods(self):
        content = (
            "service UserService {\n  rpc GetUser (GetUserRequest) returns (User);\n"
            "  rpc CreateUser (CreateUserRequest) returns (User);\n}"
        )
        result = self.parser.analyze_file("service.proto", content)
        assert len(result.endpoints) == 2
        assert result.endpoints[0]["method"] == "rpc" and result.endpoints[0]["path"] == "UserService.GetUser"
        assert result.endpoints[1]["path"] == "UserService.CreateUser"


# --- TerraformParser --------------------------------------------------------

class TestTerraformParser:
    parser = TerraformParser()

    def test_extracts_resource_blocks(self):
        content = (
            'resource "aws_s3_bucket" "main" {\n  bucket = "my-bucket"\n}\n\n'
            'resource "aws_iam_role" "lambda" {\n  name = "lambda-role"\n}'
        )
        result = self.parser.analyze_file("main.tf", content)
        assert len(result.resources) == 2
        assert result.resources[0]["name"] == "aws_s3_bucket.main" and result.resources[0]["kind"] == "aws_s3_bucket"
        assert result.resources[1]["name"] == "aws_iam_role.lambda" and result.resources[1]["kind"] == "aws_iam_role"

    def test_extracts_data_blocks(self):
        content = 'data "aws_ami" "ubuntu" {\n  most_recent = true\n}'
        result = self.parser.analyze_file("data.tf", content)
        assert any(r["name"] == "data.aws_ami.ubuntu" for r in result.resources)

    def test_extracts_module_blocks(self):
        content = 'module "vpc" {\n  source = "./modules/vpc"\n}'
        result = self.parser.analyze_file("modules.tf", content)
        assert any(r["name"] == "module.vpc" and r["kind"] == "module" for r in result.resources)

    def test_extracts_variables_and_outputs(self):
        content = 'variable "region" {\n  default = "us-east-1"\n}\n\noutput "bucket_arn" {\n  value = aws_s3_bucket.main.arn\n}'
        result = self.parser.analyze_file("variables.tf", content)
        assert any(d["name"] == "region" and d["kind"] == "variable" for d in result.definitions)
        assert any(d["name"] == "bucket_arn" and d["kind"] == "output" for d in result.definitions)


# --- MakefileParser ---------------------------------------------------------

class TestMakefileParser:
    parser = MakefileParser()

    def test_extracts_make_targets(self):
        content = "build:\n\tgo build -o bin/app\n\ntest:\n\tgo test ./...\n\nclean:\n\trm -rf bin/"
        result = self.parser.analyze_file("Makefile", content)
        assert len(result.steps) == 3
        assert [s["name"] for s in result.steps] == ["build", "test", "clean"]

    def test_ignores_variable_assignments(self):
        content = "CC := gcc\nCFLAGS := -Wall\n\nbuild:\n\t$(CC) $(CFLAGS) main.c"
        result = self.parser.analyze_file("Makefile", content)
        assert len(result.steps) == 1
        assert result.steps[0]["name"] == "build"

    def test_does_not_extract_phony(self):
        content = ".PHONY: build test\n\nbuild:\n\tgo build\n\ntest:\n\tgo test"
        result = self.parser.analyze_file("Makefile", content)
        names = [s["name"] for s in result.steps]
        assert ".PHONY" not in names
        assert "build" in names and "test" in names


# --- ShellParser ------------------------------------------------------------

class TestShellParser:
    parser = ShellParser()

    def test_extracts_function_definitions(self):
        content = '#!/bin/bash\n\ngreet() {\n  echo "Hello $1"\n}\n\nfunction cleanup {\n  rm -rf tmp/\n}'
        result = self.parser.analyze_file("script.sh", content)
        assert len(result.functions) == 2
        assert result.functions[0]["name"] == "greet"
        assert result.functions[1]["name"] == "cleanup"

    def test_extracts_source_references(self):
        content = "#!/bin/bash\nsource ./lib/utils.sh\n. ./lib/config.sh"
        refs = self.parser.extract_references("script.sh", content)
        assert len(refs) == 2
        assert refs[0]["target"] == "./lib/utils.sh" and refs[0]["referenceType"] == "file"
        assert refs[1]["target"] == "./lib/config.sh"

    def test_function_with_brace_next_line(self):
        content = 'greet()\n{\n  echo "Hello"\n}'
        result = self.parser.analyze_file("script.sh", content)
        assert len(result.functions) == 1
        assert result.functions[0]["name"] == "greet"
        assert result.functions[0]["lineRange"][1] > result.functions[0]["lineRange"][0]

    def test_rejects_function_like_without_brace(self):
        content = "\n".join(
            ["name() echo hi", "say_usage() # comment, no brace", "real_func() {", "  echo real", "}"]
        )
        result = self.parser.analyze_file("script.sh", content)
        assert [f["name"] for f in result.functions] == ["real_func"]

    def test_declares_jenkinsfile(self):
        assert "shell" in self.parser.languages and "jenkinsfile" in self.parser.languages
