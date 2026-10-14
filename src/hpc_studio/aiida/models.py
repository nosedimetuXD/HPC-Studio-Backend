"""AiiDA-compatible provenance data models for HPC Studio."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from hpc_studio.crystallography.models import CrystalStructure
from hpc_studio.qe.output.parser import QEOutputParser
from hpc_studio.qe.parser import parse_qe_input


class NodeType(str, Enum):
    """AiiDA Node types representing data and calculation nodes."""

    CALCULATION = "CALCULATION"
    STRUCTURE = "STRUCTURE"
    PSEUDO = "PSEUDO"
    PARAMETERS = "PARAMETERS"
    KPOINTS = "KPOINTS"
    BANDS = "BANDS"
    TRAJECTORY = "TRAJECTORY"
    OUTPUT_PARAMETERS = "OUTPUT_PARAMETERS"


class LinkType(str, Enum):
    """AiiDA Link types representing DAG edges."""

    INPUT_CALC = "INPUT_CALC"
    CREATE = "CREATE"
    RETURN = "RETURN"
    CALL = "CALL"


@dataclass
class DAGNode:
    """A single node in an AiiDA-compatible provenance graph."""

    node_id: int
    uuid: str
    node_type: NodeType
    label: str
    description: str = ""
    ctime: str = ""
    mtime: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.uuid:
            self.uuid = str(uuid.uuid4())
        if not self.ctime:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.ctime = now_iso
            if not self.mtime:
                self.mtime = now_iso
        elif not self.mtime:
            self.mtime = self.ctime

        if isinstance(self.node_type, str) and not isinstance(self.node_type, NodeType):
            self.node_type = NodeType(self.node_type)

    @property
    def badge_color(self) -> str:
        """Hex color code representing the node type for UI rendering."""
        color_map: dict[NodeType, str] = {
            NodeType.CALCULATION: "#2563EB",  # Blue
            NodeType.STRUCTURE: "#10B981",    # Emerald
            NodeType.PSEUDO: "#F59E0B",       # Amber
            NodeType.PARAMETERS: "#8B5CF6",   # Purple
            NodeType.KPOINTS: "#06B6D4",      # Cyan
            NodeType.BANDS: "#EC4899",        # Pink
            NodeType.TRAJECTORY: "#14B8A6",   # Teal
            NodeType.OUTPUT_PARAMETERS: "#6366F1",  # Indigo
        }
        return color_map.get(self.node_type, "#64748B")

    @property
    def type_name(self) -> str:
        """Human-readable or AiiDA-like type name for the node."""
        type_name_map: dict[NodeType, str] = {
            NodeType.CALCULATION: "CalcJobNode",
            NodeType.STRUCTURE: "StructureData",
            NodeType.PSEUDO: "UpfData",
            NodeType.PARAMETERS: "Dict (Input)",
            NodeType.KPOINTS: "KpointsData",
            NodeType.BANDS: "BandsData",
            NodeType.TRAJECTORY: "TrajectoryData",
            NodeType.OUTPUT_PARAMETERS: "Dict (Output)",
        }
        return type_name_map.get(self.node_type, self.node_type.value)


@dataclass
class DAGEdge:
    """A directed edge in the provenance graph."""

    source_id: int
    target_id: int
    link_type: LinkType
    link_label: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.link_type, str) and not isinstance(self.link_type, LinkType):
            self.link_type = LinkType(self.link_type)


@dataclass
class ProvenanceGraph:
    """AiiDA-compatible Directed Acyclic Graph (DAG) of calculation provenance."""

    nodes: dict[int, DAGNode] = field(default_factory=dict)
    edges: list[DAGEdge] = field(default_factory=list)

    def add_node(self, node: DAGNode) -> None:
        """Add a DAGNode to the provenance graph."""
        self.nodes[node.node_id] = node

    def add_edge(self, edge: DAGEdge) -> None:
        """Add a DAGEdge connecting two nodes in the provenance graph."""
        self.edges.append(edge)

    def get_incoming(self, node_id: int) -> list[DAGNode]:
        """Return all nodes that have edges pointing directly into node_id."""
        incoming_ids = [
            edge.source_id for edge in self.edges if edge.target_id == node_id
        ]
        return [self.nodes[src_id] for src_id in incoming_ids if src_id in self.nodes]

    def get_outgoing(self, node_id: int) -> list[DAGNode]:
        """Return all nodes that node_id has edges pointing directly to."""
        outgoing_ids = [
            edge.target_id for edge in self.edges if edge.source_id == node_id
        ]
        return [self.nodes[tgt_id] for tgt_id in outgoing_ids if tgt_id in self.nodes]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the provenance graph to a dictionary."""
        return {
            "nodes": [
                {
                    "node_id": node.node_id,
                    "uuid": node.uuid,
                    "node_type": node.node_type.value,
                    "label": node.label,
                    "description": node.description,
                    "ctime": node.ctime,
                    "mtime": node.mtime,
                    "attributes": node.attributes,
                    "badge_color": node.badge_color,
                    "type_name": node.type_name,
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "link_type": edge.link_type.value,
                    "link_label": edge.link_label,
                }
                for edge in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceGraph:
        """Deserialize a dictionary into a ProvenanceGraph instance."""
        graph = cls()
        nodes_data = data.get("nodes", [])
        edges_data = data.get("edges", [])

        for n_data in nodes_data:
            node = DAGNode(
                node_id=n_data["node_id"],
                uuid=n_data["uuid"],
                node_type=NodeType(n_data["node_type"]),
                label=n_data["label"],
                description=n_data.get("description", ""),
                ctime=n_data.get("ctime", ""),
                mtime=n_data.get("mtime", ""),
                attributes=n_data.get("attributes", {}),
            )
            graph.add_node(node)

        for e_data in edges_data:
            edge = DAGEdge(
                source_id=e_data["source_id"],
                target_id=e_data["target_id"],
                link_type=LinkType(e_data["link_type"]),
                link_label=e_data.get("link_label", ""),
            )
            graph.add_edge(edge)

        return graph

    @classmethod
    def from_calculation_run(
        cls,
        calc_name: str,
        qe_input_text: str,
        qe_output_text: Optional[str] = None,
    ) -> ProvenanceGraph:
        """Generate a valid provenance graph from a calculation run.

        Nodes created:
          Inputs ->
            - StructureData: chemical formula and cell/positions
            - UpfData: pseudo potentials for each species
            - Dict: input namelists / parameters
            - KpointsData: k-point grid or path
          Calculation ->
            - PwCalculation (CALCULATION)
          Outputs ->
            - Dict (OUTPUT_PARAMETERS): energies, convergence, timings
            - BandsData (if band structure is present)
            - StructureData (if relaxed structure is present)
            - TrajectoryData (if ionic relaxation steps are present)
        """
        graph = cls()
        current_id = 1

        # Parse QE input
        input_ast = parse_qe_input(qe_input_text)
        calc_type = input_ast.control.calculation or "scf"

        # 1. StructureData (input structure)
        structure_node_id = current_id
        current_id += 1
        formula = ""
        positions_count = len(input_ast.atomic_positions.positions)
        species_symbols = [sp.symbol for sp in input_ast.atomic_species.species]
        if species_symbols:
            formula = "".join(species_symbols)

        cell_matrix = (
            input_ast.cell_parameters.matrix if input_ast.cell_parameters else []
        )
        struct_attrs: dict[str, Any] = {
            "formula": formula,
            "num_atoms": positions_count,
            "ibrav": input_ast.system.ibrav,
            "cell_parameters": cell_matrix,
            "species": [
                {"symbol": s.symbol, "mass": s.mass, "pseudo": s.pseudo_file}
                for s in input_ast.atomic_species.species
            ],
        }
        struct_node = DAGNode(
            node_id=structure_node_id,
            uuid=str(uuid.uuid4()),
            node_type=NodeType.STRUCTURE,
            label=f"structure_in_{formula}" if formula else "structure_in",
            description=f"Input crystal structure with {positions_count} atoms",
            attributes=struct_attrs,
        )
        graph.add_node(struct_node)

        # 2. UpfData nodes for each pseudopotential
        pseudo_node_ids: list[int] = []
        for sp in input_ast.atomic_species.species:
            pseudo_id = current_id
            current_id += 1
            pseudo_node_ids.append(pseudo_id)
            p_node = DAGNode(
                node_id=pseudo_id,
                uuid=str(uuid.uuid4()),
                node_type=NodeType.PSEUDO,
                label=f"pseudo_{sp.symbol}",
                description=f"Pseudopotential for {sp.symbol} ({sp.pseudo_file})",
                attributes={
                    "element": sp.symbol,
                    "filename": sp.pseudo_file,
                    "mass": sp.mass,
                },
            )
            graph.add_node(p_node)

        # 3. Parameters node (input parameters Dict)
        params_node_id = current_id
        current_id += 1
        input_params: dict[str, Any] = {
            "CONTROL": {
                "calculation": input_ast.control.calculation,
                "prefix": input_ast.control.prefix,
                "pseudo_dir": input_ast.control.pseudo_dir,
                "outdir": input_ast.control.outdir,
            },
            "SYSTEM": {
                "ibrav": input_ast.system.ibrav,
                "nat": input_ast.system.nat,
                "ntyp": input_ast.system.ntyp,
                "ecutwfc": input_ast.system.ecutwfc,
                "ecutrho": input_ast.system.ecutrho,
            },
            "ELECTRONS": {
                "conv_thr": input_ast.electrons.conv_thr,
                "mixing_beta": input_ast.electrons.mixing_beta,
                "electron_maxstep": input_ast.electrons.electron_maxstep,
            },
        }
        if input_ast.ions:
            input_params["IONS"] = {
                "ion_dynamics": input_ast.ions.ion_dynamics,
            }
        params_node = DAGNode(
            node_id=params_node_id,
            uuid=str(uuid.uuid4()),
            node_type=NodeType.PARAMETERS,
            label="parameters_in",
            description="Quantum ESPRESSO input namelist parameters",
            attributes=input_params,
        )
        graph.add_node(params_node)

        # 4. KpointsData node
        kpoints_node_id = current_id
        current_id += 1
        kpoints_attrs: dict[str, Any] = {
            "mode": input_ast.k_points.mode,
            "grid": input_ast.k_points.grid,
            "shift": input_ast.k_points.shift,
            "points_count": len(input_ast.k_points.kpoints),
        }
        kpoints_node = DAGNode(
            node_id=kpoints_node_id,
            uuid=str(uuid.uuid4()),
            node_type=NodeType.KPOINTS,
            label="kpoints_in",
            description=f"K-points specification ({input_ast.k_points.mode})",
            attributes=kpoints_attrs,
        )
        graph.add_node(kpoints_node)

        # 5. Calculation node (PwCalculation)
        calc_node_id = current_id
        current_id += 1
        calc_node = DAGNode(
            node_id=calc_node_id,
            uuid=str(uuid.uuid4()),
            node_type=NodeType.CALCULATION,
            label=calc_name,
            description=f"Quantum ESPRESSO pw.x calculation ({calc_type})",
            attributes={
                "code": "pw.x",
                "calculation_type": calc_type,
            },
        )
        graph.add_node(calc_node)

        # Add edges from inputs to calculation
        graph.add_edge(
            DAGEdge(
                source_id=structure_node_id,
                target_id=calc_node_id,
                link_type=LinkType.INPUT_CALC,
                link_label="structure",
            )
        )
        for p_id in pseudo_node_ids:
            elem = graph.nodes[p_id].attributes.get("element", "species")
            graph.add_edge(
                DAGEdge(
                    source_id=p_id,
                    target_id=calc_node_id,
                    link_type=LinkType.INPUT_CALC,
                    link_label=f"pseudo_{elem}",
                )
            )
        graph.add_edge(
            DAGEdge(
                source_id=params_node_id,
                target_id=calc_node_id,
                link_type=LinkType.INPUT_CALC,
                link_label="parameters",
            )
        )
        graph.add_edge(
            DAGEdge(
                source_id=kpoints_node_id,
                target_id=calc_node_id,
                link_type=LinkType.INPUT_CALC,
                link_label="kpoints",
            )
        )

        # Parse QE output if provided
        if qe_output_text:
            qe_output = QEOutputParser.parse_string(qe_output_text)

            # 6. Output parameters node
            out_params_id = current_id
            current_id += 1
            out_attrs: dict[str, Any] = {
                "status": qe_output.status.value,
                "is_converged": qe_output.is_converged,
                "total_energy_ry": qe_output.total_energy_ry,
                "total_energy_ev": qe_output.total_energy_ev,
                "fermi_energy_ev": qe_output.fermi_energy_ev,
                "wall_time": qe_output.wall_time,
                "cpu_time": qe_output.cpu_time,
                "scf_iterations": len(qe_output.scf_history),
                "ionic_steps": len(qe_output.ionic_steps),
            }
            out_params_node = DAGNode(
                node_id=out_params_id,
                uuid=str(uuid.uuid4()),
                node_type=NodeType.OUTPUT_PARAMETERS,
                label="output_parameters",
                description="Parsed Quantum ESPRESSO output scalar results",
                attributes=out_attrs,
            )
            graph.add_node(out_params_node)
            graph.add_edge(
                DAGEdge(
                    source_id=calc_node_id,
                    target_id=out_params_id,
                    link_type=LinkType.CREATE,
                    link_label="output_parameters",
                )
            )

            # 7. BandsData node (if bands available)
            if qe_output.band_structure and qe_output.band_structure.eigenvalues_ev:
                bands_id = current_id
                current_id += 1
                bands_attrs = {
                    "num_kpoints": len(qe_output.band_structure.kpoints),
                    "num_bands": len(qe_output.band_structure.eigenvalues_ev[0])
                    if qe_output.band_structure.eigenvalues_ev
                    else 0,
                    "band_gap_ev": qe_output.band_structure.band_gap_ev,
                    "is_direct_gap": qe_output.band_structure.is_direct_gap,
                    "fermi_energy_ev": qe_output.band_structure.fermi_energy_ev,
                }
                bands_node = DAGNode(
                    node_id=bands_id,
                    uuid=str(uuid.uuid4()),
                    node_type=NodeType.BANDS,
                    label="output_bands",
                    description="Electronic band structure eigenvalues",
                    attributes=bands_attrs,
                )
                graph.add_node(bands_node)
                graph.add_edge(
                    DAGEdge(
                        source_id=calc_node_id,
                        target_id=bands_id,
                        link_type=LinkType.CREATE,
                        link_label="output_bands",
                    )
                )

            # 8. Relaxed structure (if final_structure available)
            if qe_output.final_structure:
                relaxed_id = current_id
                current_id += 1
                rel_struct = qe_output.final_structure
                rel_attrs = {
                    "chemical_formula": rel_struct.chemical_formula,
                    "num_atoms": len(rel_struct.atoms),
                    "cell_volume": rel_struct.unit_cell.volume if rel_struct.unit_cell else None,
                }
                relaxed_node = DAGNode(
                    node_id=relaxed_id,
                    uuid=str(uuid.uuid4()),
                    node_type=NodeType.STRUCTURE,
                    label=f"structure_relaxed_{rel_struct.chemical_formula}",
                    description="Relaxed crystal structure from calculation output",
                    attributes=rel_attrs,
                )
                graph.add_node(relaxed_node)
                graph.add_edge(
                    DAGEdge(
                        source_id=calc_node_id,
                        target_id=relaxed_id,
                        link_type=LinkType.CREATE,
                        link_label="output_structure",
                    )
                )

            # 9. TrajectoryData (if ionic relaxation steps > 1)
            if len(qe_output.ionic_steps) > 1:
                traj_id = current_id
                current_id += 1
                traj_node = DAGNode(
                    node_id=traj_id,
                    uuid=str(uuid.uuid4()),
                    node_type=NodeType.TRAJECTORY,
                    label="trajectory",
                    description=f"Ionic relaxation trajectory ({len(qe_output.ionic_steps)} steps)",
                    attributes={"num_steps": len(qe_output.ionic_steps)},
                )
                graph.add_node(traj_node)
                graph.add_edge(
                    DAGEdge(
                        source_id=calc_node_id,
                        target_id=traj_id,
                        link_type=LinkType.CREATE,
                        link_label="output_trajectory",
                    )
                )

        return graph
