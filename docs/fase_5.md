# **HPC Studio Linux — Especificación Detallada de Requisitos**
## **Fase 5: Distribución Nativa Linux, Telemetría HPC Avanzada y Pipelines Cuánticos Autónomos**

---

## 📌 1. Visión General de la Fase 5

La **Fase 5** expande la estación de trabajo **HPC Studio Linux** hacia el nivel de despliegue institucional y automatización autónoma de alto rendimiento para centros de supercómputo y laboratorios de investigación.

Tras la exitosa integración del núcleo SSH/SFTP (Fase 1), el motor cuántico/3D (Fase 2), los notebooks interactivos nativos (Fase 3) y la orquestación Slurm/AiiDA (Fase 4), la Fase 5 aborda:

1. **Empaquetado Universal y Distribución Linux:** Creación de instaladores nativos portables (`AppImage`, `Flatpak`, `.deb`, `.rpm`) con registro oficial de tipos MIME (`chemical/x-cif`, `chemical/x-quantum-espresso`, `.ipynb`) e integración FreeDesktop XDG.
2. **Telemetría de Supercómputo en Tiempo Real:** Monitorización en vivo del hardware remoto en ejecución (memoria por cgroup de Slurm, telemetría NVIDIA NVML/`nvidia-smi` de GPUs: VRAM, uso de SM, temperatura y consumo energético en Watts).
3. **Pipelines Cuánticos Autónomos (High-Throughput DFT):** Orquestación encadenada multi-etapa (`vc-relax` -> `scf` -> `bands` / `dos`) con propagación automática de geometrías y dependencias Slurm (`--dependency=afterok:`).
4. **Auto-Recuperación de Cálculos y Presets Institucionales:** Detección de fallos de convergencia electrónica SCF con ajuste automático de parámetros (`mixing_beta`, `smearing`, `diagonalization`) y biblioteca de perfiles de conexión para supercomputadores estándar.

---

## 🏗️ 2. Desglose Estructurado de Sprints de la Fase 5

| Sprint | Módulo / Alcance | Enfoque de Ingeniería |
| :--- | :--- | :--- |
| **Sprint 5.1** | **Empaquetado Universal Linux y Despliegue Nativo** | Manifiestos Flatpak, recetas AppImage, packaging DEB/RPM, integración con FreeDesktop XDG (iconos hicolor, asociaciones MIME, `.desktop`). |
| **Sprint 5.2** | **Telemetría HPC Avanzada en Vivo (GPU, CPU, cgroups y Energía)** | Sonda asíncrona de telemetría remota (`sstat`, `nvidia-smi`), modelo fuertemente tipado de métricas, y dock de telemetría en tiempo real con alertas de saturación de memoria. |
| **Sprint 5.3** | **Motor Autónomo de Pipelines de Simulación DFT (High-Throughput)** | Diseñador visual de secuencias DFT, propagación automática de estructuras atómicas relajadas y generador de dependencias Slurm. |
| **Sprint 5.4** | **Motor de Auto-Recuperación de Cálculos y Presets Institucionales** | Algoritmo heurístico de corrección ante divergencia SCF/OOM y catálogo de perfiles de clúster preconfigurados. |
