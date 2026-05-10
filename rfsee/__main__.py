from io import BytesIO
from typing import cast
from dataclasses import dataclass, field
import xml.etree.ElementTree as etree
from pathlib import Path
import gzip
import graphviz
import click
from enum import Enum

NAMESPACES = {"": "https://www.rfc-editor.org/rfc-index"}


class Standard(Enum):
    NIC = 0
    RFC = 1
    IEN = 2
    RTR = 3


@dataclass
class StandardIdentifier:
    type_: Standard
    num: int

    def __str__(self) -> str:
        return f"{self.type_.name}{self.num}"


def extract_rfc_num(ref: str) -> StandardIdentifier:
    types = {variant.name: variant for variant in Standard}
    for prefix, type_ in types.items():
        if ref.startswith(prefix):
            return StandardIdentifier(type_=type_, num=int(ref[3:]))

    assert False, f"Unknown standard identifier {ref}"


DEFAULT_RFC_INDEX = Path(__file__).parent / "rfc-index.xml.gz"


@click.command()
@click.option(
    "--rfc-number",
    "-n",
    help="The RFC number to graph e.g. 5321",
    type=int,
    required=True,
)
@click.option(
    "--rfc-index",
    "-i",
    help="Use an RFC index.xml file from disk. Defaults to a pre-packed index file. Get a new copy from https://www.rfc-editor.org/rfc-index.xml",
)
@click.option(
    "--output",
    "-o",
    help="Where to output the graph. Default: rfsee.dot",
    default="rfsee.dot",
)
@click.option(
    "--dont-open", help="Don't automatically open the generated graph.", is_flag=True
)
@click.option(
    "--max-depth", help="Maximum dependency exploration depth. Default: 3", default=3
)
def main(
    rfc_index: str | None, rfc_number: int, output: str, dont_open: bool, max_depth: int
):
    if rfc_index is None:
        with open(DEFAULT_RFC_INDEX, "rb") as file:
            rfc_object = BytesIO(gzip.decompress(file.read()))
    else:
        rfc_object = Path(rfc_index)
        if not rfc_object.exists():
            print(f"The provided RFC_INDEX path doesn't exist: {rfc_index}")
            return
    assert rfc_object is not None

    xml = etree.parse(rfc_object)
    rfc_index_elements = xml.getroot()
    assert rfc_index_elements is not None

    rfc_entries = rfc_index_elements.findall("rfc-entry", namespaces=NAMESPACES)
    assert rfc_entries is not None and len(rfc_entries) > 0

    @dataclass
    class RfcEntry:
        standard: StandardIdentifier
        title: str
        updates: list[StandardIdentifier] = field(default_factory=list)
        updated_by: list[StandardIdentifier] = field(default_factory=list)
        obsoletes: list[StandardIdentifier] = field(default_factory=list)
        obsoleted_by: list[StandardIdentifier] = field(default_factory=list)
        see_also: list[StandardIdentifier] = field(default_factory=list)

    reference_fields = [
        "updates",
        "updated-by",
        "obsoletes",
        "obsoleted-by",
        "see-also",
    ]

    rfcs: dict[int, RfcEntry] = {}
    for entry in rfc_entries:
        docid_node = entry.find("doc-id", namespaces=NAMESPACES)
        assert docid_node is not None and docid_node.text is not None
        standard = extract_rfc_num(docid_node.text)
        assert standard.type_ == Standard.RFC

        title_node = entry.find("title", namespaces=NAMESPACES)
        assert title_node is not None and title_node.text is not None
        title = title_node.text

        reference_results = {}
        for field_name in reference_fields:
            reference_nodes = entry.find(field_name, namespaces=NAMESPACES)
            if reference_nodes is not None:
                docs = reference_nodes.findall("doc-id", namespaces=NAMESPACES)
                assert docs is not None and len(docs) > 0
                reference_results[field_name.replace("-", "_")] = [
                    extract_rfc_num(cast("str", doc.text)) for doc in docs
                ]

        rfcs[standard.num] = RfcEntry(
            standard=standard,
            title=title,
            **reference_results,
        )

    node = rfcs.get(rfc_number)
    if node is None:
        print(
            f"No known RFC with index number {rfc_number}. Are you sure this is real?"
        )
        return

    dot = graphviz.Digraph(f"Graph for {node}")

    visited: list[StandardIdentifier] = []

    def recurse_nodes(entry: RfcEntry, depth=0):
        dot.node(str(entry.standard), f"{str(entry.standard)}: {entry.title}")
        visited.append(entry.standard)

        if depth >= max_depth:
            return

        for field_name in reference_fields:
            nodes: list[StandardIdentifier] = getattr(
                entry, field_name.replace("-", "_")
            )
            for node in nodes:
                if node not in visited:
                    dot.edge(str(entry.standard), str(node), label=field_name)
                    if node.type_ == Standard.RFC:
                        next_ = rfcs.get(node.num)
                        if next_ is None:
                            print(
                                f"{entry.standard} references {node} which doesn't exist?!"
                            )
                            exit()

                        recurse_nodes(next_, depth=depth + 1)
                    else:
                        dot.node(str(node), str(node))
                        visited.append(node)

    recurse_nodes(node)

    dot = dot.unflatten(stagger=3)
    dot.render(output, view=not dont_open)


if __name__ == "__main__":
    main()
