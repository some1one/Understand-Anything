"""Port of ``configs/xml.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

xml_config = LanguageConfig(
    id="xml",
    displayName="XML",
    extensions=[".xml", ".xsl", ".xsd", ".svg", ".plist"],
    concepts=["elements", "attributes", "namespaces", "DTD", "XPath", "XSLT", "schemas"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": ["pom.xml", "web.xml", "AndroidManifest.xml"],
    },
)
