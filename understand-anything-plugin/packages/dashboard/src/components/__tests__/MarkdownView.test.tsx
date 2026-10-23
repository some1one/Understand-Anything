import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MarkdownView } from "../CodeViewer";

describe("Markdown source preview", () => {
  it("renders headings, GFM tables, task lists, and fenced source", () => {
    const html = renderToStaticMarkup(<MarkdownView content={[
      "# Project", "", "| Name | Value |", "| --- | --- |", "| API | Ready |",
      "", "- [x] Complete", "", "```ts", "const value = 1;", "```",
    ].join("\n")} />);
    expect(html).toContain(">Project</h1>");
    expect(html).toContain("<table");
    expect(html).toContain(">API</td>");
    expect(html).toContain('type="checkbox"');
    expect(html).toContain('checked=""');
    expect(html).toContain('class="language-ts"');
    expect(html).toContain("const value = 1;");
  });

  it("treats embedded HTML as source and filters unsafe link URLs", () => {
    const html = renderToStaticMarkup(<MarkdownView content={'<script>alert(1)</script>\n\n[bad](javascript:alert%281%29)\n\n[Docs](https://example.org/docs)'} />);
    expect(html).not.toContain("<script>");
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain('href="https://example.org/docs"');
    expect(html).toContain('rel="noreferrer"');
  });
});
