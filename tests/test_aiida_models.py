"""Unit tests for AiiDA provenance data models and graph construction."""

import pytest

from hpc_studio.aiida.models import (
    DAGEdge,
    DAGNode,
    LinkType,
    NodeType,
    ProvenanceGraph,
)


def test_dagnode_initialization_and_properties():
    node = DAGNode(
        node_id=1,
        uuid="",
        node_type=NodeType.CALCULATION,
        label="pw_scf",
        description="Self-consistent calculation",
    )
    assert node.node_id == 1
    assert len(node.uuid) > 0
    assert node.node_type == NodeType.CALCULATION
    assert node.type_name == "CalcJobNode"
    assert node.badge_color == "#2563EB"
    assert len(node.ctime) > 0
    assert node.mtime == node.ctime


def test_dagnode_colors_and_type_names():
    type_checks = [
        (NodeType.CALCULATION, "#2563EB", "CalcJobNode"),
        (NodeType.STRUCTURE, "#10B981", "StructureData"),
        (NodeType.PSEUDO, "#F59E0B", "UpfData"),
        (NodeType.PARAMETERS, "#8B5CF6", "Dict (Input)"),
        (NodeType.KPOINTS, "#06B6D4", "KpointsData"),
        (NodeType.BANDS, "#EC4899", "BandsData"),
        (NodeType.TRAJECTORY, "#14B8A6", "TrajectoryData"),
        (NodeType.OUTPUT_PARAMETERS, "#6366F1", "Dict (Output)"),
    ]
    for n_type, expected_color, expected_name in type_checks:
        node = DAGNode(node_id=10, uuid="abc", node_type=n_type, label="test")
        assert node.badge_color == expected_color
        assert node.type_name == expected_name


def test_dagedge_initialization():
    edge = DAGEdge(
        source_id=1,
        target_id=2,
        link_type=LinkType.INPUT_CALC,
        link_label="structure",
    )
    assert edge.source_id == 1
    assert edge.target_id == 2
    assert edge.link_type == LinkType.INPUT_CALC
    assert edge.link_label == "structure"


def test_provenance_graph_add_and_traversal():
    graph = ProvenanceGraph()

    n1 = DAGNode(node_id=1, uuid="u1", node_type=NodeType.STRUCTURE, label="struct")
    n2 = DAGNode(node_id=2, uuid="u2", node_type=NodeType.CALCULATION, label="calc")
    n3 = DAGNode(node_id=3, uuid="u3", node_type=NodeType.OUTPUT_PARAMETERS, label="out")

    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)

    e1 = DAGEdge(source_id=1, target_id=2, link_type=LinkType.INPUT_CALC)
    e2 = DAGEdge(source_id=2, target_id=3, link_type=LinkType.CREATE)

    graph.add_edge(e1)
    graph.add_edge(e2)

    # Topological traversal check
    incoming_to_calc = graph.get_incoming(2)
    assert len(incoming_to_calc) == 1
    assert incoming_to_calc[0].node_id == 1

    outgoing_from_calc = graph.get_outgoing(2)
    assert len(outgoing_from_calc) == 1
    assert outgoing_from_calc[0].node_id == 3

    assert len(graph.get_incoming(1)) == 0
    assert len(graph.get_outgoing(3)) == 0


def test_provenance_graph_serialization_roundtrip():
    graph = ProvenanceGraph()
    n1 = DAGNode(node_id=1, uuid="uuid-1", node_type=NodeType.STRUCTURE, label="Si")
    n2 = DAGNode(node_id=2, uuid="uuid-2", node_type=NodeType.CALCULATION, label="pw.x")
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_edge(DAGEdge(source_id=1, target_id=2, link_type=LinkType.INPUT_CALC, link_label="structure"))

    serialized = graph.to_dict()
    assert "nodes" in serialized
    assert "edges" in serialized
    assert len(serialized["nodes"]) == 2
    assert len(serialized["edges"]) == 1

    restored = ProvenanceGraph.from_dict(serialized)
    assert len(restored.nodes) == 2
    assert len(restored.edges) == 1
    assert restored.nodes[1].label == "Si"
    assert restored.nodes[2].label == "pw.x"
    assert restored.edges[0].link_label == "structure"


def test_from_calculation_run_input_only():
    qe_input = """&CONTROL
  calculation = 'scf'
  pseudo_dir = './pseudo'
  outdir = './out'
  prefix = 'si'
/
&SYSTEM
  ibrav = 2
  celldm(1) = 10.26
  nat = 2
  ntyp = 1
  ecutwfc = 30.0
/
&ELECTRONS
  conv_thr = 1.0d-8
/
ATOMIC_SPECIES
  Si 28.0855 Si.pbe.UPF
ATOMIC_POSITIONS crystal
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25
K_POINTS automatic
  4 4 4 0 0 0
"""
    graph = ProvenanceGraph.from_calculation_run(
        calc_name="pw_si_scf",
        qe_input_text=qe_input,
    )

    # Check created nodes
    node_types = [n.node_type for n in graph.nodes.values()]
    assert NodeType.STRUCTURE in node_types
    assert NodeType.PSEUDO in node_types
    assert NodeType.PARAMETERS in node_types
    assert NodeType.KPOINTS in node_types
    assert NodeType.CALCULATION in node_types

    # Find calculation node
    calc_nodes = [n for n in graph.nodes.values() if n.node_type == NodeType.CALCULATION]
    assert len(calc_nodes) == 1
    calc_id = calc_nodes[0].node_id

    # Inputs should point to calculation
    incoming = graph.get_incoming(calc_id)
    assert len(incoming) == 4  # structure, pseudo_Si, parameters, kpoints
    assert len(graph.get_outgoing(calc_id)) == 0  # No output provided


def test_from_calculation_run_with_output():
    qe_input = """&CONTROL
  calculation = 'relax'
  prefix = 'silicon'
/
&SYSTEM
  ibrav = 2
  celldm(1) = 10.26
  nat = 2
  ntyp = 1
  ecutwfc = 30.0
/
&ELECTRONS
  conv_thr = 1.0d-8
/
&IONS
  ion_dynamics = 'bfgs'
/
ATOMIC_SPECIES
  Si 28.0855 Si.pbe.UPF
ATOMIC_POSITIONS crystal
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25
K_POINTS automatic
  4 4 4 0 0 0
"""
    qe_output = """Program PWSCF v.6.8 starts
  Self-consistent Calculation
  iteration #  1 ecut=   30.00 Ry
  total cpu time spent up to now is      0.2 secs
  total energy              =     -15.84234567 Ry
  estimated scf accuracy    <       0.00123456 Ry
  End of self-consistent calculation
  !    total energy              =     -15.84300000 Ry
  convergence has been achieved in   2 iterations
  JOB DONE.
"""
    graph = ProvenanceGraph.from_calculation_run(
        calc_name="silicon_relax",
        qe_input_text=qe_input,
        qe_output_text=qe_output,
    )

    node_types = [n.node_type for n in graph.nodes.values()]
    assert NodeType.OUTPUT_PARAMETERS in node_types

    calc_node = [n for n in graph.nodes.values() if n.node_type == NodeType.CALCULATION][0]
    outgoing = graph.get_outgoing(calc_node.node_id)
    assert any(n.node_type == NodeType.OUTPUT_PARAMETERS for n in outgoing)
