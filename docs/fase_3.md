# 📓 HPC Studio Linux — Especificación Detallada de Requisitos
## **Fase 3: Integración Nativa de Jupyter Notebooks (`.ipynb`) con Kernels Locales y Remotos vía SSH**

---

## 📌 1. Visión General y Alcance de la Fase 3

La **Fase 3** transforma a **HPC Studio Linux** en un entorno científico interactivo unificado, integrando la ejecución y edición de **Jupyter Notebooks (`.ipynb`)** como ciudadanos de primer nivel dentro del IDE. 

A diferencia de las interfaces tradicionales basadas en navegador (JupyterLab web) que requieren abrir puertos, gestionar túneles HTTP manuales y consumir cientos de megabytes en procesos de Chromium, **HPC Studio** ejecuta y renderiza los notebooks de forma **completamente nativa en Qt6 / PySide6**. Se conecta a los kernels mediante el protocolo **Jupyter Messaging Protocol v5.x sobre ZeroMQ (pyzmq)** tanto localmente como sobre canales **SSH cifrados directos** hacia los nodos de cómputo del supercomputador.

```
+-----------------------------------------------------------------------------------------+
|                                    HPC STUDIO IDE                                       |
|  +-----------------------------------------------------------------------------------+  |
|  | Jupyter Notebook Native Canvas (Qt6)                                              |  |
|  | [In 1]: import ase, matplotlib ...  [▶ Ejecutar] [⏹ Interrumpir] [🔄 Reiniciar]  |  |
|  | [Out 1]: <Renderizado Nativo: Markdown, LaTeX KaTeX, SVG, Matplotlib, Plotly, 3D>|  |
|  +-----------------------------------------------------------------------------------+  |
|                                         ▲                                               |
|                    Jupyter Client Engine (Async Qt / Python 3.12)                       |
|                                         │                                               |
|               +-------------------------+-------------------------+                     |
|               │                                                   │                     |
|        [Kernel Local]                                      [Kernel Remoto SSH]          |
|    Local IPykernel Process                             Paramiko Direct-TCP / ZMQ        |
|    ~/.local/share/jupyter/kernels                      HPC Node (Slurm / Login)         |
|    Direct ZMQ IPC / TCP (Loopback)                     Port Forwarding Dinámico         |
+-----------------------------------------------------------------------------------------+
```

---

## 🏗️ 2. Desglose Estructurado de Sprints de la Fase 3

Para garantizar entregas verificables, incrementales y con 100% de cobertura de pruebas, la Fase 3 se subdivide en **4 Sprints Técnicos**:

| Sprint | Módulo / Alcance | Enfoque de Ingeniería | Estado |
| :--- | :--- | :--- | :---: |
| **Sprint 3.1** | **Motor de Documento `.ipynb` (JSON v4) & Renderizador de Celdas Qt6** | Modelo de datos in-memory, parseo/serialización nbformat v4, soporte de celdas Code, Markdown y Raw, renderizado enriquecido (texto plano, streams, errores ANSI coloreados, imágenes PNG/JPEG/SVG, HTML sanitizado y fórmulas matemáticas LaTeX). | ✅ **Completado (100%)** (21/21 tests) |
| **Sprint 3.2** | **Gestor de Kernels Locales & Protocolo ZeroMQ (ZMQ)** | Descubrimiento de `kernelspecs` en Linux (`/usr/share/jupyter/kernels`, `~/.local/share/jupyter/kernels`), ciclo de vida (`start`, `interrupt`, `restart`, `shutdown`), comunicación multicanal ZMQ (`shell`, `iopub`, `stdin`, `control`, `heartbeat`) con autenticación HMAC-SHA256. | ⏳ Pendiente |
| **Sprint 3.3** | **Túnel SSH y Kernels Remotos en Nodos HPC** | Descubrimiento y arranque de kernels remotos en clústeres SSH (entornos Conda / venv / módulos Lmod remotos), reenvío dinámico de puertos ZMQ (`direct-tcpip` sobre Paramiko), reconexión automática ante latencia o pérdida de red. | ⏳ Pendiente |
| **Sprint 3.4** | **Interactividad Avanzada, Widgets Científicos & Exportación** | Autocompletado de código (`complete_request`), inspección de objetos (`inspect_request`), integración con visualizador 3D cristalográfico nativo para objetos ASE/Pymatgen, y exportación bidireccional a scripts `.py` y templates de simulación Slurm/QE. | ⏳ Pendiente |

---

## 📋 3. Requisitos Funcionales Detallados (RF)

### 🔹 Sprint 3.1: Motor de Documento `.ipynb` & Canvas de Celdas

* **RF-3.1.1 (Parser y Validador nbformat v4):**
  - Carga y serialización estricta de archivos `.ipynb` conforme al esquema oficial **Jupyter Notebook Format v4.5**.
  - Preservación íntegra de metadatos globales (`metadata.kernelspec`, `metadata.language_info`) y metadatos individuales por celda (`tags`, `collapsed`, `scrolled`, `id`).
  - Detección y migración transparente de notebooks antiguos (v3 a v4).
  - Manejo de fallos con respaldo de seguridad atómico para evitar corrupción de datos durante el guardado.

* **RF-3.1.2 (Modelo de Celdas y Jerarquía Visual):**
  - `NotebookModel(QObject)`: Modelo reactivo que emite señales de celda agregada, eliminada, movida y modificada.
  - Tipos de celda soportados:
    1. **Code Cell:** Editor con numeración de líneas, coloreado de sintaxis Python (resaltador nativo derivado de `CodeEditor`), contador de ejecución (`In [n]`), área de salidas colapsable.
    2. **Markdown Cell:** Vista dual (modo edición con QPlainTextEdit y modo renderizado con formato enriquecido, encabezados, listas, bloques de código con tipografía monoespaciada).
    3. **Raw Cell:** Texto plano sin procesar preservado para exportadores (`nbconvert`).

* **RF-3.1.3 (Renderizador de Salidas Múltiples `MIMETypeRenderer`):**
  - Soporte de MIME types estándar:
    * `text/plain`: Texto estándar con soporte de saltos de línea y wrapping.
    * `application/vnd.jupyter.stderr` & `text/plain`: Salidas de error y warnings renderizadas con el parser ANSI de HPC Studio (`TerminalANSIParser`), mapeando los colores a la paleta del IDE.
    * `image/png`, `image/jpeg`: Escalado de imágenes respetando DPI de pantalla y aspect ratio.
    * `image/svg+xml`: Renderizado vectorial nítido con `PySide6.QtSvg.QSvgRenderer`.
    * `text/html`: Subconjunto seguro de HTML formateado (tablas de `pandas`, DataFrames, sumarios de modelos).
    * `text/latex`: Fórmulas matemáticas inline ($...$) y display ($$...$$) renderizadas mediante motor KaTeX/MathJax incrustado o generación vectorial local.

* **RF-3.1.4 (Ergonomía de Edición y Atajos Estándar Jupyter):**
  - Modos de interacción duales:
    * **Modo Comando (Azul/Gris):** Navegación con flechas `Up`/`Down` o `j`/`k`, insertar celda arriba (`A`), insertar celda abajo (`B`), eliminar celda (`D, D`), cambiar a Markdown (`M`), cambiar a Código (`Y`).
    * **Modo Edición (Verde/Resaltado):** Activación con `Enter`, salida con `Esc`.
  - Atajos de ejecución: `Shift+Enter` (ejecutar y avanzar), `Ctrl+Enter` (ejecutar celda actual), `Alt+Enter` (ejecutar e insertar abajo).

---

### 🔹 Sprint 3.2: Gestor de Kernels Locales & Protocolo ZeroMQ (COMPLETADO)

* **RF-3.2.1 (Detección de Kernelspecs en el Sistema):**
  - Exploración automática de rutas estándar en Linux:
    * Entorno activo (`sys.prefix/share/jupyter/kernels`).
    * Usuario (`~/.local/share/jupyter/kernels`).
    * Sistema (`/usr/share/jupyter/kernels`, `/usr/local/share/jupyter/kernels`).
  - Parseo de `kernel.json` para extraer nombre de visualización (`display_name`), lenguaje (`language`), ejecutable de Python (`argv`) y variables de entorno (`env`).
  - Detección de entornos virtuales locales (venv de HPC Studio, Conda, Mamba, uv).

* **RF-3.2.2 (Ciclo de Vida del Proceso de Kernel Local):**
  - Generación dinámica de `connection_file.json` con puertos efímeros libres asignados por el sistema operativo para los 5 canales de ZMQ:
    * `shell_port`: Peticiones de ejecución, completado e inspección (ROUTER/DEALER).
    * `iopub_port`: Difusión de salidas, streams de texto, display data y estado (PUB/SUB).
    * `stdin_port`: Entrada de usuario interactiva para `input()` o prompts (ROUTER/DEALER).
    * `control_port`: Comandos de alta prioridad como shutdown o interrupción (ROUTER/DEALER).
    * `hb_port`: Heartbeat de monitorización de vida del kernel (REQ/REP).
  - Arranque del subproceso con aislamiento seguro (`subprocess.Popen` sin shell, preservando grupos de procesos con `setsid` para evitar procesos huérfanos).
  - Generación de clave secreta aleatoria criptográfica para firmas **HMAC-SHA256**.

* **RF-3.2.3 (Cliente Jupyter Asíncrono sobre ZeroMQ):**
  - Implementación multihilo con `pyzmq`:
    * Hilo `IOPubListener`: Escucha continua en segundo plano para procesar ráfagas de datos sin bloquear la interfaz de usuario de Qt.
    * Hilo `HeartbeatMonitor`: Envío periódico de pings con temporizador configurable; detección de cuelgues o kernel muerto (*Dead Kernel*) en menos de 3 segundos.
  - Conversión de mensajes ZMQ estructurados hacia señales de Qt (`kernel_status_changed`, `execution_output_received`, `execution_completed`, `input_requested`).

* **RF-3.2.4 (Controles de Ejecución en la Barra de Herramientas):**
  - Botón *Ejecutar Celda* (`play`), *Ejecutar Todo*, *Interrumpir Kernel* (`close`/`stop`), *Reiniciar Kernel* (`refresh`), *Limpiar Todas las Salidas*.
  - Selector desplegable de Kernel con indicación del estado: *Idle* (círculo gris/verde), *Busy* (spinner/animación de cómputo), *Starting*, *Dead*.

---

### 🔹 Sprint 3.3: Conectividad y Kernels Remotos sobre SSH (COMPLETADO)

* **RF-3.3.1 (Arranque de Kernel Remoto en Clúster HPC):**
  - Inicio de un proceso `ipykernel` en el nodo remoto a través del `SSHClientManager` existente.
  - Soporte para inicialización de entornos remotos:
    * Carga de módulos de entorno (`module load python/3.11`, `module load py-scipy`).
    * Activación de entornos remotos (`source /scratch/$USER/env/bin/activate` o `conda activate dft_env`).
  - Creación del archivo de conexión remoto en una ubicación segura temporal (`/tmp` o `~/.cache/hpc_studio/kernels/`).

* **RF-3.3.2 (Multiplexación y Túnel de Puertos ZMQ vía Paramiko):**
  - Enrutamiento dinámico de los 5 puertos ZeroMQ a través de canales directos SSH (`direct-tcpip`):
    * `Local Loopback Port` $\leftrightarrow$ `SSH Tunnel` $\leftrightarrow$ `Remote Host Port`.
  - Reutilización de la autenticación de sesión de la Fase 1 sin requerir volver a ingresar credenciales ni abrir puertos públicos en el firewall del clúster.

* **RF-3.3.3 (Tolerancia a Latencia y Reconexión Automática):**
  - Buffer de cola para encolar celdas pendientes en caso de microcortes de red.
  - Watchdog de latencia con telemetría en la barra de estado (*Ping Remoto: XX ms*).
  - Terminación remota limpia del kernel al cerrar el documento o salir del IDE para no dejar procesos consumiendo memoria en los nodos de login o particiones de cómputo.

---

### 🔹 Sprint 3.4: Interactividad Avanzada, Visualización y Exportación (COMPLETADO)

* **RF-3.4.1 (Intellisense, Autocompletado e Inspección):**
  - Envío de peticiones `complete_request` al kernel al pulsar la tecla `Tab`.
  - Despliegue de popup de autocompletado nativo con sugerencias de métodos, atributos y módulos.
  - Envío de `inspect_request` al pulsar `Shift+Tab` para desplegar el docstring y la firma de la función en un tooltip contextual.

* **RF-3.4.2 (Visualización Científica Integrada 3D y Gráficos):**
  - Intercepción de objetos de estructuras moleculares y cristalinas (objetos `ase.Atoms` o `pymatgen.core.Structure` devueltos en una celda).
  - Opción de renderizado con un clic: *Abrir en Visualizador 3D Nativo (`CrystalViewerWidget`)* directamente desde la salida del notebook.
  - Soporte de renderizado de gráficos vectoriales interactivos para librerías científicas (`matplotlib`, `seaborn`, `plotly`).

* **RF-3.4.3 (Herramientas de Exportación y Conversión de Código):**
  - **Exportar a Script Python (`.py`):** Extracción limpia de todas las celdas de código, eliminando números mágicos y convirtiendo celdas Markdown en comentarios estructurados.
  - **Exportar a Script Slurm (`.sbatch`):** Conversión automática del script resultante en un trabajo por lotes listo para enviarse a la cola de Slurm, inyectando encabezados `#SBATCH`.
  - **Generación de Inputs Quantum ESPRESSO:** Integración con el motor de la Fase 2 para que un notebook que prepare estructuras atómicas pueda exportar directamente archivos `.in` de `pw.x`.

---

## 🔒 4. Requisitos No Funcionales (RNF) y Seguridad

* **RNF-3.1 (Aislamiento y Sanitización de Contenidos - CWE-79 / XSS):**
  - Cuando se rendericen salidas ricas en formato `text/html`, se debe aplicar sanitización estricta para bloquear scripts ejecutables embebidos (`<script>`, eventos `onload=`, `javascript:` URIs) que puedan intentar acceder al sistema de archivos local del usuario.
* **RNF-3.2 (Rendimiento y Consumo de Memoria - Límite de Buffer):**
  - Salidas de streaming excesivas (por ejemplo, bucles infinitos con `print()`) deben truncarse de forma segura tras **50,000 líneas** o **10 MB**, mostrando una advertencia al usuario y evitando el congelamiento de la GUI.
* **RNF-3.3 (Criptografía y Verificación de Mensajes ZMQ):**
  - Todos los mensajes ZMQ intercambiados con kernels locales y remotos deben ir autenticados mediante firmas **HMAC-SHA256**. No se aceptarán mensajes con firmas vacías o inválidas.
* **RNF-3.4 (Concurrencia y Reactividad de Interfaz):**
  - Las operaciones de red, sockets ZMQ y túneles SSH deben residir exclusivamente en hilos secundarios de trabajo (`QThread` / `threading.Thread`), garantizando que la interfaz permanezca fluida a **60 FPS** incluso durante la ejecución de simulaciones pesadas.
* **RNF-3.5 (Compatibilidad Estricta de Temas e Íconos Vectoriales):**
  - Respeto total al motor `ThemeEngine`: todos los componentes de notebook (bordes de celdas, fondos de editor, gutters, bloques de código, textos matemáticos) deben reaccionar al cambio entre tema Claro y tema Oscuro.
  - Cero emojis en botones, tabs, diálogos y notificaciones: uso exclusivo de los íconos vectoriales SVG de `src/hpc_studio/ui/icons.py`.

---

## 🏛️ 5. Arquitectura de Módulos Propuesta

```
src/hpc_studio/
├── notebook/                              # [NUEVO SUBSISTEMA FASE 3]
│   ├── __init__.py
│   ├── models.py                          # NotebookDocument, CellModel, OutputData, MimeBundle
│   ├── parser.py                          # Serializador / Deserializador nbformat v4
│   ├── kernel_spec.py                     # Buscador y parser de kernel.json del sistema
│   ├── kernel_client.py                   # Abstracción base del cliente de kernel
│   ├── local_kernel.py                    # Gestor de kernel local (subproceso + ZMQ)
│   ├── remote_kernel.py                   # Gestor de kernel remoto (SSH direct-tcpip + ZMQ)
│   ├── zmq_channels.py                    # Handlers de canales shell, iopub, stdin, control, hb
│   └── exporter.py                        # Exportador a Python (.py), Slurm (.sbatch) y HTML
│
└── ui/
    ├── notebook/                          # [NUEVA CAPA UI FASE 3]
    │   ├── __init__.py
    │   ├── notebook_editor.py             # Widget central del notebook (NotebookCanvas)
    │   ├── cell_widget.py                 # Widget de celda individual (Code / Markdown / Raw)
    │   ├── cell_output_widget.py          # Renderizador de outputs múltiples (MIME dispatcher)
    │   ├── markdown_highlighter.py        # Resaltador de sintaxis Markdown / LaTeX
    │   ├── kernel_selector_widget.py      # Selector y widget de estado de kernel
    │   └── intellisense_popup.py          # Popups de autocompletado e inspección
```

---

## 🧪 6. Estrategia de Pruebas y Validación

La Fase 3 se integrará en la suite automatizada de `pytest` bajo `tests/`:

1. **`tests/test_notebook_models.py`:** Pruebas de serialización/deserialización nbformat v4, inserción, eliminación y mutación de celdas, persistencia de metadata.
2. **`tests/test_notebook_parser.py`:** Pruebas de compatibilidad con notebooks reales (v4.0 - v4.5), recuperación ante archivos corruptos o malformados.
3. **`tests/test_kernel_specs.py`:** Detección de kernels locales en entornos Linux, lectura de `kernel.json`, resolución de ejecutables de Python.
4. **`tests/test_zmq_protocol.py`:** Simulación de sockets ZMQ con stubs, verificación de firmas HMAC-SHA256, parseo de mensajes de cabecera y contenido.
5. **`tests/test_local_kernel_lifecycle.py`:** Arranque real/mockeado de `ipykernel`, envío de `execute_request`, recepción de streams de `stdout` y terminación limpia.
6. **`tests/test_remote_kernel_tunnel.py`:** Pruebas del túnel Paramiko `direct-tcpip`, reenvío de puertos efímeros y control de caídas de conexión.
7. **`tests/test_notebook_ui.py`:** Pruebas de interfaz gráfica con `pytest-qt` / `QTest`: renderizado de celdas, alternancia de modos comando/edición, visualización de imágenes y gráficos, cambio de tema Claro/Oscuro y verificación de cero emojis.

---

## 🎯 7. Definición de Hecho (Definition of Done) para la Fase 3

- [ ] Soporte completo para abrir, editar, guardar y crear notebooks `.ipynb` (JSON v4) en pestañas del IDE.
- [ ] Ejecución interactiva de celdas con kernels locales (`ipykernel`) reportando estado en tiempo real.
- [ ] Conexión y ejecución sobre kernels remotos en clústeres HPC mediante túnel SSH transparente.
- [ ] Renderizado nítido de salidas de texto, errores ANSI formateados, tablas HTML, imágenes PNG/SVG y expresiones matemáticas LaTeX.
- [ ] Autocompletado de código (Tab) e inspección de firmas (Shift+Tab).
- [ ] Exportación a scripts `.py` limpios y plantillas de envío Slurm `.sbatch`.
- [ ] Cobertura de pruebas unitarias e integrales superior al 95% manteniendo las 322 pruebas anteriores pasando al 100%.
- [ ] Cumplimiento total de la política de cero emojis e integración perfecta con el tema visual de HPC Studio.
