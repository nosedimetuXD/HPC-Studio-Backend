# Catálogo Formal de Herramientas MCP de HPC Studio

**Servidor:** HPC Studio Model Context Protocol (MCP) Server  
**Ubicación de Implementación:** [`src/hpc_studio/mcp/tools.py`](file:///home/nosedimetuxd/Proyectos/HPC%20Studio/src/hpc_studio/mcp/tools.py)  
**Versión de Protocolo:** Model Context Protocol (JSON-RPC 2.0 / MCP 2024-11-05)  
**Total de Herramientas Expuestas:** 9 herramientas especializadas para cálculo científico y HPC.

---

## 1. Arquitectura del Servidor MCP

El servidor MCP de HPC Studio expone las capacidades del entorno de supercómputo y ciencia de materiales a agentes de inteligencia artificial (como Antigravity / Claude / GPT) mediante una interfaz de llamada a herramientas (Tool Calling) fuertemente tipada y sanitizada.

```text
┌──────────────────────────────────────────────┐
│        AI Agent (Antigravity / LLM)          │
└──────────────────────┬───────────────────────┘
                       │ JSON-RPC 2.0 (stdio / SSE)
┌──────────────────────▼───────────────────────┐
│        HPC Studio MCP Server Engine          │
│        (ToolRegistry & Sanitizers)           │
├──────────────────────┬───────────────────────┤
│ Clúster & Slurm      │ Ciencia de Materiales │
│  - hpc_slurm_queue   │  - hpc_validate_qe    │
│  - hpc_slurm_submit  │  - hpc_inspect_struct │
│  - hpc_slurm_cancel  │ Sistema de Archivos   │
│  - hpc_slurm_log     │  - hpc_sftp_list      │
│  - hpc_list_clusters │  - hpc_sftp_read      │
└──────────────────────┴───────────────────────┘
```

---

## 2. Catálogo Detallado de Herramientas

---

### Herramienta 1: `hpc_slurm_queue`

* **Nombre:** `hpc_slurm_queue`
* **Descripción:** Consulta la cola de trabajos del gestor de carga Slurm en el clúster activo o entorno local con filtros opcionales de partición y usuario.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "partition": {
      "type": "string",
      "description": "Nombre de la partición de Slurm a filtrar (ej. 'gpu', 'normal', 'debug')."
    },
    "user": {
      "type": "string",
      "description": "Nombre de usuario Slurm para limitar la consulta."
    }
  },
  "required": []
}
```
* **Estructura de Retorno:**
```json
{
  "total_jobs": 1,
  "jobs": [
    {
      "job_id": "101",
      "name": "silicon_scf",
      "user": "max",
      "state": "RUNNING",
      "time_used": "00:04:12",
      "time_limit": "02:00:00",
      "nodes": "1",
      "cpus": "4",
      "reason": "None",
      "work_dir": "/home/max/calculations/silicon",
      "nodelist": "node01"
    }
  ],
  "filter": {
    "user": "max",
    "partition": null
  }
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "hpc_slurm_queue",
    "arguments": {
      "user": "max"
    }
  }
}
```
* **Casos de Uso para Agentes:** Diagnosticar si un cálculo encolado está retenido por cuota (`ReqNodeNotAvail`), monitorear tiempos de finalización o verificar la disponibilidad de nodos antes de lanzar una tanda de cálculos.

---

### Herramienta 2: `hpc_slurm_submit`

* **Nombre:** `hpc_slurm_submit`
* **Descripción:** Valida la estructura del script y envía un trabajo por lotes a la cola de Slurm mediante el comando `sbatch`.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "script_path": {
      "type": "string",
      "description": "Ruta local o remota al archivo de script batch (.sbatch, .slurm o .sh)."
    },
    "script_content": {
      "type": "string",
      "description": "Contenido textual directo del script de envío por lotes si se genera en memoria."
    }
  },
  "required": []
}
```
* **Estructura de Retorno:**
```json
{
  "status": "submitted",
  "job_id": "102",
  "raw_output": "Submitted batch job 102",
  "script_used": "/home/max/calculations/run_scf.slurm"
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "hpc_slurm_submit",
    "arguments": {
      "script_path": "/home/max/calculations/run_scf.slurm"
    }
  }
}
```
* **Casos de Uso para Agentes:** Automatizar la ejecución autónoma de simulaciones tras optimizar hiperparámetros o tras resolver errores en archivos de entrada.

---

### Herramienta 3: `hpc_slurm_cancel`

* **Nombre:** `hpc_slurm_cancel`
* **Descripción:** Cancela un trabajo de Slurm en estado de ejecución o pendiente mediante `scancel`, permitiendo especificar una señal POSIX opcional.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "job_id": {
      "type": "string",
      "description": "Identificador único del trabajo Slurm a cancelar (ej. '102' o '102_1')."
    },
    "signal": {
      "type": "string",
      "description": "Nombre de la señal POSIX a transmitir (ej. 'SIGTERM', 'SIGKILL', '9')."
    }
  },
  "required": ["job_id"]
}
```
* **Estructura de Retorno:**
```json
{
  "status": "cancelled",
  "job_id": "102",
  "signal": "SIGTERM",
  "message": "Job 102 cancelled successfully"
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "hpc_slurm_cancel",
    "arguments": {
      "job_id": "102",
      "signal": "SIGTERM"
    }
  }
}
```
* **Casos de Uso para Agentes:** Abortar cálculos divergentes que desperdician horas de CPU (core-hours) o cancelar tareas con dependencias fallidas.

---

### Herramienta 4: `hpc_slurm_log`

* **Nombre:** `hpc_slurm_log`
* **Descripción:** Lee las líneas de salida estándar o de error (`stdout`/`stderr`) asociadas a un cálculo en Slurm.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "log_path": {
      "type": "string",
      "description": "Ruta absoluta o relativa al archivo de registro (ej. 'slurm-101.out')."
    },
    "lines": {
      "type": "integer",
      "description": "Número de líneas finales a recuperar (por defecto: 50)."
    }
  },
  "required": ["log_path"]
}
```
* **Estructura de Retorno:**
```json
{
  "path": "/home/max/calculations/slurm-101.out",
  "lines_requested": 50,
  "lines_returned": 18,
  "content": "iteration # 1 ... total energy = -15.82 Ry\niteration # 5 ... total energy = -15.84 Ry\nJOB DONE.\n"
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "hpc_slurm_log",
    "arguments": {
      "log_path": "/home/max/calculations/slurm-101.out",
      "lines": 30
    }
  }
}
```
* **Casos de Uso para Agentes:** Inspección en vivo para detectar errores de convergencia SCF, caídas por Out-Of-Memory (OOM) o problemas de comunicación MPI en tiempo de ejecución.

---

### Herramienta 5: `hpc_validate_qe`

* **Nombre:** `hpc_validate_qe`
* **Descripción:** Validación sintáctica y semántica estricta de archivos de entrada de Quantum ESPRESSO (`pw.x`), verificando namelists requeridas (`&CONTROL`, `&SYSTEM`, `&ELECTRONS`), concordancia de especies atómicas y consistencia de mallas K.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "input_path": {
      "type": "string",
      "description": "Ruta al archivo de entrada de Quantum ESPRESSO (.in, .pwi)."
    },
    "input_content": {
      "type": "string",
      "description": "Contenido textual directo del archivo de entrada de Quantum ESPRESSO."
    }
  },
  "required": []
}
```
* **Estructura de Retorno:**
```json
{
  "valid": true,
  "errors": [],
  "warnings": [
    "High ecutwfc (120 Ry) for PAW pseudopotential may incur significant computational overhead."
  ],
  "summary": {
    "calculation": "scf",
    "ibrav": 2,
    "nat": 2,
    "ntyp": 1,
    "ecutwfc": 30.0,
    "species": ["Si"]
  }
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "hpc_validate_qe",
    "arguments": {
      "input_path": "/home/nosedimetuxd/Proyectos/HPC Studio/samples/silicon_scf.in"
    }
  }
}
```
* **Casos de Uso para Agentes:** Validación preventiva antes de gastar recursos de cómputo en supercomputadores, asegurando que los parámetros físicos y las rutas sean coherentes.

---

### Herramienta 6: `hpc_inspect_structure`

* **Nombre:** `hpc_inspect_structure`
* **Descripción:** Análisis cristalográfico de archivos de estructura atómica (`.cif` y `.xyz`). Extrae parámetros de celda ($a, b, c, \alpha, \beta, \gamma$), volumen unitario, recuento de especies y fórmula química reducida.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string",
      "description": "Ruta al archivo cristalográfico (.cif o .xyz)."
    },
    "file_content": {
      "type": "string",
      "description": "Contenido textual directo del archivo de estructura."
    },
    "format": {
      "type": "string",
      "enum": ["cif", "xyz"],
      "description": "Formato de archivo explícito si la extensión no es representativa."
    }
  },
  "required": []
}
```
* **Estructura de Retorno:**
```json
{
  "format": "cif",
  "formula": "Si2",
  "atom_count": 2,
  "species_counts": {
    "Si": 2
  },
  "lattice": {
    "a": 5.4307,
    "b": 5.4307,
    "c": 5.4307,
    "alpha": 90.0,
    "beta": 90.0,
    "gamma": 90.0,
    "volume": 160.18
  },
  "symmetry": {
    "space_group_name": "F d -3 m",
    "space_group_number": 227
  }
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "hpc_inspect_structure",
    "arguments": {
      "file_path": "/home/nosedimetuxd/Proyectos/HPC Studio/samples/silicon_diamond.cif"
    }
  }
}
```
* **Casos de Uso para Agentes:** Extraer automáticamente los parámetros de red necesarios para rellenar las tarjetas `celldm(1)` y `ATOMIC_POSITIONS` al convertir archivos CIF a inputs de Quantum ESPRESSO.

---

### Herramienta 7: `hpc_list_clusters`

* **Nombre:** `hpc_list_clusters`
* **Descripción:** Recupera la lista de clústeres remotos configurados en `~/.ssh/config` y presets de emulación de cómputo local (como Quantum Mobile en `127.0.0.1:2222`).
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```
* **Estructura de Retorno:**
```json
{
  "clusters": [
    {
      "name": "Quantum Mobile (VirtualBox)",
      "hostname": "127.0.0.1",
      "port": 2222,
      "user": "max",
      "description": "Local simulation VM for materials science"
    },
    {
      "name": "marenostrum5",
      "hostname": "mn1.bsc.es",
      "port": 22,
      "user": "bscuser21",
      "description": "Production Tier-0 Supercomputer"
    }
  ],
  "active_cluster": {
    "hostname": "127.0.0.1",
    "port": 2222,
    "user": "max",
    "status": "connected"
  }
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "hpc_list_clusters",
    "arguments": {}
  }
}
```
* **Casos de Uso para Agentes:** Descubrir clústeres disponibles para sugerir destinos de ejecución alternativos cuando una partición local no disponga de GPUs.

---

### Herramienta 8: `hpc_sftp_list`

* **Nombre:** `hpc_sftp_list`
* **Descripción:** Lista archivos y subdirectorios en el sistema de archivos del clúster remoto activo vía SFTP.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Ruta del directorio remoto a explorar (por defecto: '.')."
    },
    "limit": {
      "type": "integer",
      "description": "Número máximo de entradas a listar (por defecto: 100)."
    }
  },
  "required": []
}
```
* **Estructura de Retorno:**
```json
{
  "path": "/home/max/calculations",
  "total_items": 3,
  "items": [
    {
      "name": "silicon_scf.in",
      "path": "/home/max/calculations/silicon_scf.in",
      "is_dir": false,
      "size": 650,
      "permissions": "-rw-r--r--",
      "mtime": 1729124400
    },
    {
      "name": "out",
      "path": "/home/max/calculations/out",
      "is_dir": true,
      "size": 4096,
      "permissions": "drwxr-xr-x",
      "mtime": 1729124500
    }
  ]
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 8,
  "method": "tools/call",
  "params": {
    "name": "hpc_sftp_list",
    "arguments": {
      "path": "/home/max/calculations",
      "limit": 50
    }
  }
}
```
* **Casos de Uso para Agentes:** Explorar carpetas remotas para localizar archivos de densidad de carga (`.save`), matrices dinámicas de fonones o logs generados por simulaciones complejas.

---

### Herramienta 9: `hpc_sftp_read`

* **Nombre:** `hpc_sftp_read`
* **Descripción:** Lee el contenido de un archivo en el clúster remoto con paginación por líneas, evitando saturar la memoria o el contexto del LLM con archivos masivos.
* **Esquema de Parámetros de Entrada (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Ruta remota absoluta o relativa del archivo a leer."
    },
    "offset": {
      "type": "integer",
      "description": "Número de línea inicial (1-indexed, por defecto: 1)."
    },
    "limit": {
      "type": "integer",
      "description": "Cantidad máxima de líneas a recuperar (por defecto: 200)."
    }
  },
  "required": ["path"]
}
```
* **Estructura de Retorno:**
```json
{
  "path": "/home/max/calculations/silicon.out",
  "total_lines": 850,
  "offset": 800,
  "lines_read": 51,
  "content": "     PWSCF        :     3.45s CPU         3.80s WALL\n\n   This run was terminated on:  12:30:15  17Oct2026\n\n=------------------------------------------------------------------------------=\n   JOB DONE.\n=------------------------------------------------------------------------------="
}
```
* **Ejemplo de Llamada JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 9,
  "method": "tools/call",
  "params": {
    "name": "hpc_sftp_read",
    "arguments": {
      "path": "/home/max/calculations/silicon.out",
      "offset": 800,
      "limit": 60
    }
  }
}
```
* **Casos de Uso para Agentes:** Inspeccionar archivos de salida masivos de Quantum ESPRESSO o Gaussian directamente en el almacenamiento del clúster sin necesidad de descargar gigabytes de datos a la máquina local.
