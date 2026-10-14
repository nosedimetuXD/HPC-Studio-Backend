# HPC Studio Backend

**High Performance Computing (HPC) & Quantum Sidecar Backend**

FastAPI and Python backend engine for High Performance Computing (HPC), quantum/materials simulations (Quantum ESPRESSO), Slurm orchestration, interactive Jupyter kernels, and SSH/SFTP cluster connectivity.

## Modules & Architecture
- **Server (`hpc_studio.server`)**: FastAPI HTTP & WebSocket API, authentication, and event manager.
- **SSH & SFTP (`hpc_studio.ssh`, `hpc_studio.sftp`)**: Remote cluster connectivity, tunnels, and async file transfers.
- **Slurm Engine (`hpc_studio.slurm`)**: Job generation, cluster queue monitoring, log follower, and watchdog.
- **Quantum Workbench (`hpc_studio.qe`, `hpc_studio.crystallography`)**: QE input generators, parsers, and CIF/XYZ structure engines.
- **Notebook Execution (`hpc_studio.notebook`)**: Local and remote ZeroMQ Jupyter kernel runtimes and exporters.
- **AI Agent (`hpc_studio.agent`)**: HPC autonomous assistant engine with specialized HPC tools.
- **Core System (`hpc_studio.core`)**: Configuration, state serialization, notifications, and event bus.
