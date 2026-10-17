# ESPECIFICACIÓN DE REQUISITOS DE SOFTWARE (ERS)
## Conforme a la Norma Internacional ISO/IEC/IEEE 29148:2018

**Proyecto:** HPC Studio - Integrated Development Environment for High-Performance Scientific Computing  
**Documento:** Especificación Formal de Requisitos del Sistema y Software (ERS/SyRS)  
**Versión:** 1.0.0  
**Fecha de Emisión:** 17 de Octubre de 2026  
**Clasificación:** Ingeniería de Requisitos / Estándar Académico e Industrial  
**Normas de Referencia:** ISO/IEC/IEEE 29148:2018 & ISO/IEC 25010:2011 (SQuaRE)  
**Autores:** Equipo de Arquitectura de Sistemas HPC Studio & División de Documentación Científica  

---

## 1. Introducción

### 1.1 Propósito
El presente documento constituye la **Especificación de Requisitos de Software (ERS)** formal para la plataforma **HPC Studio**, formulada con estricto apego a las directrices metodológicas de la norma **ISO/IEC/IEEE 29148:2018** (*Systems and software engineering — Life cycle processes — Requirements engineering*) y los modelos de calidad sistémica definidos en **ISO/IEC 25010:2011** (*SQuaRE*).

El propósito primordial de esta especificación es definir de manera exhaustiva, cuantitativa, no ambigua y verificable las capacidades operativas, interfaces externas, restricciones de arquitectura, propiedades de seguridad y atributos de calidad que rigen el ecosistema HPC Studio. Este artefacto sirve como contrato de ingeniería y base contractual entre investigadores computacionales, científicos de materiales, administradores de clústeres HPC, ingenieros de software e implementadores de agentes autónomos.

### 1.2 Ámbito del Producto (Scope)
**Nombre del Producto:** *HPC Studio* (Entorno Integrado de Computación Científica de Alto Rendimiento).

#### Objetivos Estratégicos:
1. **Unificación del Flujo de Trabajo Científico:** Integrar en una única interfaz de grado profesional el desarrollo de scripts de simulación, la gestión de conexiones de red a supercomputadores remotos, la supervisión de colas Slurm y el análisis visual de estructuras cristalográficas y moleculares.
2. **Mitigación de la Brecha de Usabilidad en HPC:** Eliminar la fricción cognitiva asociada al uso manual de terminales SSH desacopladas, edición ciega de tarjetas de entrada Quantum ESPRESSO y scripts sbatch, ofreciendo sincronización bidireccional, validaciones semánticas y visores 3D reactivos.
3. **Automatización Mediante Agentes Inteligentes:** Proveer una arquitectura de interoperabilidad abierta sustentada en el protocolo Model Context Protocol (MCP) y el agente autónomo Google Antigravity, permitiendo la delegación segura de tareas complejas de supercómputo y diagnóstico de errores en clústeres.

#### Límites del Sistema:
* **Dentro del Alcance (In-Scope):**
  - Cliente IDE de escritorio basado en el fork de VS Code optimizado con extensiones integradas de HPC.
  - Extensión principal de VS Code (`hpc-studio`) escrita en TypeScript, gestora de vistas de árbol, editores personalizados y puente de comunicación.
  - Servidor demonio sidecar local desarrollado en Python 3.12+ con FastAPI y Uvicorn, encargado de la orquestación SSH, túneles, SFTP, monitoreo Slurm y streaming reactivo.
  - Servidor oficial Model Context Protocol (MCP) stdio con 9 herramientas especializadas de supercómputo.
  - Integración nativa del agente Antigravity mediante invocación por subprocesos aislados y streaming de chat interactivo.
  - Módulos de visualización cristalográfica 3D acelerada por hardware WebGL para archivos `.cif` y `.xyz`.
  - Servidor de sintaxis y diagnóstico para Quantum ESPRESSO (`.in`, `.out`, `.pwi`, `.pwo`), Slurm (`.slurm`, `.sbatch`) y Pseudopotenciales UPF (`.upf`, `.UPF`).
* **Fuera del Alcance (Out-of-Scope):**
  - Sustitución o reimplementación de demonios nativos de Slurm (`slurmctld`, `slurmd`) en los clústeres remotos.
  - Reemplazo de los motores de primeros principios (ej. binarios Fortran/C de Quantum ESPRESSO o AiiDA core).
  - Gestión física o aprovisionamiento bare-metal de hardware en centros de datos.

### 1.3 Visión General del Producto

#### 1.3.1 Perspectiva del Producto
HPC Studio opera como un sistema híbrido céntrico en el cliente, estructurado en tres capas desacopladas que garantizan robustez, seguridad y reactividad:
1. **Frontend / Presentación (IDE Workbench):** Fork de VS Code que aloja la interfaz gráfica, árboles de exploración (`Remote Clusters & SSH`, `Slurm Queue Monitor`, `Cluster File Transfer`), paneles de estado y Custom Text Editors para rendering 3D.
2. **Middleware / Orquestación (Python Sidecar Daemon):** Proceso local independiente que expone una API REST y canales WebSocket protegidos mediante tokens efímeros. Se comunica con el frontend vía HTTP/WS sobre loopback (`127.0.0.1`).
3. **Capa de Infraestructura Remota (Supercómputo / Slurm / SFTP):** Nodos maestros y clústeres HPC externos accesibles a través de canales SSH seguros (OpenSSH v2), ejecutando comandos no interactivos o interactivos mediante túneles seguros.

```
+-----------------------------------------------------------------------+
|                             HPC STUDIO                                |
|  +-----------------------------------------------------------------+  |
|  |                 VS Code Fork Client (Workbench)                 |  |
|  |  +---------------------+  +-----------------+  +-------------+  |  |
|  |  | Tree Views          |  | Custom Editor   |  | Chat Window |  |  |
|  |  | Clusters/Slurm/SFTP |  | WebGL 3D Viewer |  | Antigravity |  |  |
|  |  +----------+----------+  +--------+--------+  +------+------+  |  |
|  +-------------|----------------------|------------------|---------+  |
|                | Loopback HTTP / WS   |                  |            |
|                | Bearer Token Auth    |                  | IPC/CLI    |
|  +-------------v----------------------v------------------|---------+  |
|  |              Python FastAPI Sidecar Daemon            |         |  |
|  |  +--------------------+  +--------------------+       |         |  |
|  |  | SSH / SFTP Worker  |  | Slurm Watchdog     |       |         |  |
|  |  | Paramiko / Tunnel  |  | RemoteLogStreamer  |       |         |  |
|  |  +--------------------+  +--------------------+       |         |  |
|  |  +--------------------------------------------+       |         |  |
|  |  | MCP Server (stdio) / 9 Herramientas HPC    |<------+         |  |
|  |  +--------------------------------------------+                 |  |
|  +-----------------------+-----------------------------------------+  |
+--------------------------|--------------------------------------------+
                           | Canal SSH Cifrado (RFC 4253)
                           v
          +----------------------------------+
          |      Clúster Remoto / HPC        |
          |  - Slurm (squeue, sbatch)        |
          |  - Sistema de Archivos SFTP      |
          |  - Quantum ESPRESSO Binarios     |
          |  - Entorno Quantum Mobile VM     |
          +----------------------------------+
```

#### 1.3.2 Funciones Principales del Producto
* Gestión del ciclo de vida y supervisión resiliente del backend Python sidecar.
* Análisis y resolución de configuraciones de red complejas mediante parseo de `~/.ssh/config`.
* Conexión con un solo clic al entorno virtualizado de simulación Quantum Mobile (VirtualBox/Docker).
* Monitoreo no bloqueante en tiempo real de colas Slurm con cancelación y despacho automatizado.
* Transmisión continua y reactiva de registros de cálculo en ejecución (`tail -f` sobre SSH).
* Navegación y transferencia bidireccional transparente de conjuntos de datos y pseudopotenciales vía SFTP.
* Renderizado 3D e inspección cristalográfica interactiva de celdas unitarias y moléculas.
* Asistencia contextual mediante Inteligencia Artificial conectada al entorno HPC vía MCP y Antigravity.

#### 1.3.3 Características de los Usuarios
* **Investigador en Ciencia de Materiales y Física del Estado Sólido:** Especialista en cálculos ab initio (DFT) con Quantum ESPRESSO; requiere validación de sintaxis, previsualización de geometrías atómicas y ejecución batch sin lidiar con comandos crudos de terminal.
* **Administrador / Operador de Sistemas HPC:** Encargado de la supervisión de cargas de trabajo en nodos de cómputo, diagnóstico de fallos en trabajos Slurm y gestión de recursos compartidos.
* **Estudiante de Posgrado / Investigador Junior:** Usuario del entorno de aprendizaje Quantum Mobile que precisa plantillas parametrizadas de cálculo y asistencia interactiva de IA.

#### 1.3.4 Limitaciones y Restricciones
* **RES-01:** La comunicación entre el frontend (TypeScript) y el backend sidecar (Python) DEBERÁ realizarse exclusivamente a través de la interfaz de red local `127.0.0.1` con puertos efímeros dinámicos.
* **RES-02:** El backend DEBERÁ ejecutarse bajo entornos aislados de Python 3.12 o 3.14 gestionados mediante el gestor de paquetes de alto rendimiento `uv`.
* **RES-03:** Las sesiones SSH DEBERÁN cumplir con la especificación SSH-2 (RFC 4253) utilizando cifrado simétrico robusto (AES-256-GCM, ChaCha20-Poly1305) y llaves asimétricas Ed25519 o RSA de mínimo 3072 bits.
* **RES-04:** Queda estrictamente prohibido el almacenamiento persistente de credenciales en texto plano; las credenciales y tokens se mantendrán exclusivamente en memoria volátil o en el almacén de secretos del sistema operativo.

### 1.4 Definiciones, Acrónimos y Abreviaturas
* **AiiDA:** *Automated Interactive Infrastructure and Database for Computational Science*.
* **API:** *Application Programming Interface*.
* **CIF:** *Crystallographic Information File* (formato estándar IUCr).
* **CLI:** *Command Line Interface*.
* **DFT:** *Density Functional Theory* (Teoría del Funcional de la Densidad).
* **ERS:** Especificación de Requisitos de Software.
* **HPC:** *High-Performance Computing* (Computación de Alto Rendimiento).
* **IDE:** *Integrated Development Environment*.
* **JSON:** *JavaScript Object Notation*.
* **MCP:** *Model Context Protocol* (estándar abierto de comunicación para agentes IA).
* **QE:** *Quantum ESPRESSO* (suite integrada de código abierto para cálculos electrónicos).
* **RF:** Requisito Funcional.
* **RNF:** Requisito No Funcional.
* **SFTP:** *SSH File Transfer Protocol*.
* **Slurm:** *Simple Linux Utility for Resource Management* (gestor de colas de cómputo).
* **SSH:** *Secure Shell*.
* **UPF:** *Unified Pseudopotential Format*.
* **URI:** *Uniform Resource Identifier*.
* **UUID:** *Universally Unique Identifier*.
* **WebGL:** *Web Graphics Library* (estándar de renderizado 3D en navegadores).
* **WS:** *WebSocket*.
* **XYZ:** Formato de coordenadas atómicas cartesianas.

---

## 2. Referencias Documentales

1. **ISO/IEC/IEEE 29148:2018:** *Systems and software engineering — Life cycle processes — Requirements engineering*.
2. **ISO/IEC 25010:2011:** *Systems and software engineering — Systems and software Quality Requirements and Evaluation (SQuaRE) — System and software quality models*.
3. **RFC 4253:** *The Secure Shell (SSH) Transport Layer Protocol*.
4. **RFC 6455:** *The WebSocket Protocol*.
5. **Model Context Protocol Specification (MCP):** *Anthropic / Linux Foundation Open Standard for Agent-Tool Interoperability, 2024-2025*.
6. **Quantum ESPRESSO Documentation:** *Input Data Description for PWscf (v7.x)*, Giannozzi et al.
7. **Slurm Workload Manager Documentation:** *SchedMD Slurm Architecture and User Guide (v23.x/24.x)*.
8. **IUCr CIF Standard:** *International Union of Crystallography Specification for CIF Files (Core Dictionary)*.

---

## 3. Requisitos Específicos

### 3.1 Interfaces Externas

#### 3.1.1 Interfaces de Usuario (UI/UX)
* **IDE Workbench:** El sistema presentará una barra de actividad lateral (*Activity Bar*) con un contenedor dedicado de HPC Studio (`hpc-studio-workbench`) que agrupa tres vistas de árbol jerárquicas:
  1. *Remote Clusters & SSH* (`hpc-studio.clustersView`): Listado de hosts remotos, estados de latencia y accesos rápidos a terminal y túneles.
  2. *Slurm Queue Monitor* (`hpc-studio.slurmQueueView`): Tabla de trabajos particionada por estados (`RUNNING`, `PENDING`, `COMPLETED`, `FAILED`, `CANCELLED`).
  3. *Cluster File Transfer (SFTP)* (`hpc-studio.sftpExplorerView`): Árbol de navegación del sistema de archivos remoto.
* **Barra de Estado (*Status Bar*):** Indicador permanente (`hpc-studio.statusBar`) que muestra el estado operativo del daemon (`RUNNING`, `STOPPED`, `STARTING`, `ERROR`), puerto activo y latencia de red.
* **Visores de Estructura 3D:** Ventanas de editor personalizado integradas (`Structure3DEditorProvider`) con controles de órbita orbital WebGL, ajuste de escala de bolas y varillas (*ball-and-stick*), vectores de celda y panel de medición de distancias atómicas.
* **Ventana de Chat del Agente:** Panel dedicado e interactivo con soporte de Markdown, bloques de código, visualizadores de diffs y botones de acción rápida.

#### 3.1.2 Interfaces de Hardware
* **Arquitectura de Procesamiento:** Arquitecturas x86_64 y ARM64 (Apple Silicon, ARM Linux).
* **Aceleración Gráfica:** Unidad de Procesamiento Gráfico (GPU) compatible con WebGL 2.0 y controladores OpenGL 3.3+ para el renderizado cristalográfico a mínimo 60 FPS.
* **Memoria RAM:** Mínimo 4 GB de memoria física disponible para el proceso IDE y 512 MB dedicados al backend sidecar.

#### 3.1.3 Interfaces de Software
* **Sistema Operativo:** GNU/Linux (kernel 5.4+), macOS (12.0+ Monterey en adelante) y Microsoft Windows 10/11 (nativo y WSL2).
* **Entorno de Ejecución:** Node.js 20+ (para el frontend de VS Code) y Python 3.12+ (para el daemon de cómputo).
* **Gestor de Entornos:** Binario `uv` para resolución instantánea de dependencias y ejecución aislada sin contaminar entornos de sistema.
* **CLI de Agente:** Ejecutable `agy` (Google Antigravity CLI) ubicado en el PATH del sistema o en `~/.local/bin/agy`.

#### 3.1.4 Interfaces de Comunicación
* **Comunicación Interna Loopback:** Protocolo HTTP/1.1 y WebSockets (RFC 6455) sobre `127.0.0.1` protegido por cabecera de autorización `X-HPC-Token` o `Authorization: Bearer <token>`.
* **Comunicación Externa hacia Supercomputadores:** Canales SSH-2 sobre TCP/IP (puertos 22 o asignados dinámicamente) soportando conexiones directas, túneles locales/remotos y saltos mediante `ProxyJump`.

---

### 3.2 Requisitos Funcionales (RF-01 a RF-20)

#### RF-01: Gestión de Ciclo de Vida del Sidecar
* **Sintaxis Formal:** El sistema DEBERÁ inicializar, autenticar, monitorear y detener limpiamente el proceso demonio en segundo plano (Python FastAPI) cuando el IDE cliente inicie, cambie de estado o sea cerrado por el usuario.
* **Entradas:** Comando de activación del IDE, configuración de puerto y host (`hpc-studio.serverHost`, `hpc-studio.serverPort`), variable `hpc-studio.autoStartSidecar`.
* **Procesamiento:**
  1. `SidecarSupervisor` detecta la ruta del intérprete Python (o binario `uv`).
  2. Genera un token criptográfico seguro de un solo uso (32 bytes urlsafe) y arranca el subproceso Python con argumentos de host, puerto dinámico (`--port 0`) y token.
  3. Captura el flujo de inicialización mediante tubería IPC leyendo el JSON de handshake emitido en stdout (`{"status": "running", "host": "127.0.0.1", "port": P, "token": T, "pid": PID}`).
  4. Inicia un ciclo periódico de sondeo de salud (*health check heartbeat*) cada 5 segundos mediante peticiones `GET /api/health`.
  5. Si el proceso termina inesperadamente, aplica una política de reintentos exponenciales con límite de 5 intentos.
  6. Al disponer el supervisor, envía señal `SIGTERM` (o `SIGKILL` tras 3 segundos de gracia) y libera los descriptores de archivo.
* **Salidas:** Estado de conexión actualizado en `HPCStatusBarItem`, canal WebSocket suscrito a eventos en tiempo real.
* **Excepciones:** En caso de fallo de arranque (ej. intérprete Python no encontrado o puerto ocupado), el sistema emitirá una notificación de error crítico con enlace a los registros detallados de salida (`OutputChannel`).

#### RF-02: Gestión de Conexiones SSH y Detección de ~/.ssh/config
* **Sintaxis Formal:** El sistema DEBERÁ analizar sintácticamente el archivo de configuración OpenSSH del usuario (`~/.ssh/config`) y poblar la vista de clústeres remotos cuando el módulo de conexiones sea cargado o se solicite una sincronización.
* **Entradas:** Ruta física al archivo de configuración SSH del usuario, contenido de texto con directivas `Host`, `HostName`, `User`, `Port`, `IdentityFile`, `ProxyJump`, `ProxyCommand`.
* **Procesamiento:**
  1. `config_parser.py` lee y normaliza las directivas del archivo respetando la regla "first-match-wins" (primer coincidencia gana) de la especificación OpenSSH.
  2. Resuelve comodines (`*`, `?`) y herencia de bloques globales.
  3. Valida la seguridad y límites de puertos (1 a 65535) y la integridad de las rutas de claves privadas.
  4. Combina los hosts encontrados con los perfiles manuales definidos en la configuración `hpc-studio.clusters`.
* **Salidas:** Lista estructurada de objetos `SSHHostEntry` serializados a la vista de árbol `hpc-studio.clustersView`.
* **Excepciones:** Si el archivo no existe o presenta permisos inseguros o caracteres de control nulos, el parser registrará un aviso en el registro de auditoría y presentará únicamente los hosts configurados manualmente sin detener el sistema.

#### RF-03: Preset de Conexión a Quantum Mobile
* **Sintaxis Formal:** El sistema DEBERÁ proporcionar y registrar automáticamente un perfil predeterminado para la máquina virtual de simulación Quantum Mobile cuando el usuario seleccione la acción rápida correspondiente en la vista de clústeres.
* **Entradas:** Acción del usuario `hpc-studio.addQuantumMobile` ejecutada desde el menú contextual o la barra de herramientas de la vista de clústeres.
* **Procesamiento:**
  1. El sistema verifica si ya existe una entrada con el identificador `Quantum Mobile (VirtualBox)`.
  2. Inyecta el perfil preconfigurado con: Hostname = `127.0.0.1`, Puerto = `2222`, Usuario = `max`, Descripción = `Local simulation VM for materials science (Quantum ESPRESSO, AiiDA, Slurm)`.
  3. Ejecuta una prueba no destructiva de sondeo TCP al socket `127.0.0.1:2222` para verificar si la máquina virtual o contenedor se encuentra encendido.
* **Salidas:** Perfil incorporado permanentemente a la configuración de clústeres, icono contextual representativo y estado de disponibilidad en línea visible.
* **Excepciones:** Si el puerto 2222 no responde en 500 ms, el sistema creará el perfil pero marcará el estado como "Desconectado", ofreciendo un botón para abrir la "Guía de Inicio y Configuración de Quantum Mobile".

#### RF-04: Monitoreo en Tiempo Real de la Cola Slurm (squeue)
* **Sintaxis Formal:** El sistema DEBERÁ consultar periódicamente el estado de la cola de planificación de trabajos del clúster remoto ejecutando `squeue` cuando el clúster objetivo esté activo y conectado.
* **Entradas:** Identificador del clúster remoto conectado, filtro opcional de usuario (`--user`) o partición (`--partition`), intervalo de actualización (por defecto 10 s).
* **Procesamiento:**
  1. El backend sidecar despacha el comando remoto formateado:  
     `squeue --noheader --format="%i|%j|%u|%T|%M|%l|%D|%R|%P"` a través del canal SSH activo.
  2. El analizador `slurm/client.py` procesa cada línea de texto separada por pipes y genera modelos `SlurmJobData`.
  3. Clasifica los trabajos en los estados formales de Slurm: `RUNNING`, `PENDING`, `COMPLETED`, `FAILED`, `CANCELLED`, `SUSPENDED`.
  4. Emite el evento a través del canal WebSocket hacia el cliente VS Code.
* **Salidas:** Árbol `Slurm Queue Monitor` actualizado reactivamente con iconos diferenciados por color temático y conteo de CPUs y tiempo de cómputo consumido.
* **Excepciones:** En caso de caída de la conexión SSH o indisponibilidad temporal del binario `squeue`, el sistema mantendrá los últimos datos conocidos en caché visual con una advertencia visual de reconexión.

#### RF-05: Envío Automatizado de Trabajos Slurm (sbatch)
* **Sintaxis Formal:** El sistema DEBERÁ transferir y encolar scripts de cálculo en el planificador Slurm ejecutando `sbatch` cuando el usuario solicite el envío de un trabajo desde el editor o explorador.
* **Entradas:** Archivo de script Slurm local o remoto (`.slurm`, `.sbatch`), parámetros opcionales de directorio de trabajo y dependencias.
* **Procesamiento:**
  1. Si el script es local, el cliente verifica su consistencia y lo transfiere vía SFTP al directorio de trabajo remoto temporal.
  2. Ejecuta remotamente el comando: `sbatch <ruta_script>`.
  3. Parsea la respuesta estándar del planificador extrayendo la expresión regular `Submitted batch job ([0-9]+)`.
  4. Registra el nuevo Job ID en la lista de seguimiento del `SlurmWatchdog`.
* **Salidas:** Notificación flotante informativa con el Job ID asignado y actualización inmediata de la vista de cola de trabajos.
* **Excepciones:** Si el comando `sbatch` retorna un código de salida distinto de cero (ej. error de directiva `#SBATCH`, límite de cuota o partición inexistente), el sistema capturará `stderr` y desplegará un modal de diagnóstico detallado.

#### RF-06: Cancelación de Trabajos en Clúster (scancel)
* **Sintaxis Formal:** El sistema DEBERÁ abortar la ejecución o encolamiento de un trabajo en el clúster ejecutando `scancel` cuando el usuario confirme la solicitud de cancelación de un trabajo en estado `RUNNING` o `PENDING`.
* **Entradas:** Identificador numérico del trabajo Slurm (`JobId`), confirmación explícita en diálogo modal de usuario.
* **Procesamiento:**
  1. El sistema valida que el trabajo pertenezca al usuario activo o posea permisos adecuados.
  2. Ejecuta el comando remoto: `scancel <JobId>`.
  3. Verifica la salida del comando y solicita una actualización forzada inmediata de la cola de trabajos.
* **Salidas:** Mensaje de confirmación en la barra de notificaciones y transición de estado del elemento en el árbol a `CANCELLED`.
* **Excepciones:** Si el trabajo ya ha finalizado en el instante de la cancelación o se produce un error de permisos, el sistema informará que el trabajo no pudo ser modificado junto con la causa reportada por Slurm.

#### RF-07: Transmisión y Seguimiento de Registros de Cálculo en Vivo (tail -f)
* **Sintaxis Formal:** El sistema DEBERÁ establecer un canal de lectura en streaming para transmitir las líneas emitidas en los archivos de salida estándar y error (`slurm-%j.out`, `qe.out`) cuando el usuario active la acción "Stream Live Output".
* **Entradas:** Ruta absoluta del archivo remoto de log o identificador del trabajo activo.
* **Procesamiento:**
  1. El módulo `RemoteLogStreamer` abre una sesión interactiva SSH sin asignación de pseudoterminal (PTY) y lanza el comando: `tail -n 100 -f <ruta_log>`.
  2. Un hilo de trabajo dedicado (`threading.Thread`) procesa el flujo entrante mediante lectura de bloques continuos.
  3. Emite cada línea a través de la señal `line_received` hacia el puente WebSocket del backend.
  4. El frontend redirige los datos entrantes hacia un panel de terminal o salida enriquecida con capacidad de pausar, reanudar y auto-scroll.
* **Salidas:** Panel de salida dinámico mostrando los registros de simulación con latencia de renderizado inferior a 200 ms.
* **Excepciones:** Si el archivo de log aún no ha sido creado por Slurm (trabajo en espera `PENDING`), el sistema reintentará la suscripción periódicamente informando: "Esperando que el nodo de cómputo cree el descriptor de salida".

#### RF-08: Exploración Remota de Archivos mediante SFTP
* **Sintaxis Formal:** El sistema DEBERÁ listar de forma recursiva bajo demanda la jerarquía de directorios y archivos de un clúster remoto mediante el protocolo SFTP cuando el usuario despliegue nodos en la vista `Cluster File Transfer`.
* **Entradas:** Ruta remota solicitada (por defecto el directorio `$HOME` del usuario remoto), credenciales o sesión SSH autenticada.
* **Procesamiento:**
  1. `sftp/client.py` solicita la apertura del subsistema `sftp` en la conexión SSH activa de Paramiko.
  2. Invoca el método `listdir_attr()` sobre el directorio solicitado.
  3. Transforma los atributos del sistema de archivos UNIX (permisos, tamaño en bytes, timestamp de modificación, nombre) en objetos `RemoteNode`.
  4. Ordena los elementos situando directorios en la parte superior y archivos alfabéticamente.
* **Salidas:** Estructura jerárquica en `hpc-studio.sftpExplorerView` con iconos representativos según la extensión del archivo (`.cif`, `.xyz`, `.in`, `.out`, `.upf`).
* **Excepciones:** Si el usuario carece de permisos de lectura en un directorio remoto (error `EACCES`), el sistema marcará el nodo como inaccesible sin bloquear la exploración de otros directorios.

#### RF-09: Transferencia Bidireccional de Archivos (Upload / Download SFTP)
* **Sintaxis Formal:** El sistema DEBERÁ transferir archivos y carpetas completas de manera bidireccional entre la máquina local y el almacenamiento del clúster remoto cuando el usuario ejecute acciones de subida o descarga.
* **Entradas:** Ruta de origen (local o remota), ruta de destino (remota o local), política de sobreescritura.
* **Procesamiento:**
  1. La cola de transferencia (`transfer_queue.py`) inicializa una tarea asíncrona de subida (`put`) o descarga (`get`).
  2. Realiza la lectura y escritura en bloques de 32 KB (*chunks*), calculando el progreso porcentual y la tasa de transferencia en MB/s.
  3. Reporta el avance de la operación mediante el sistema de notificaciones del IDE.
  4. Al finalizar la transferencia, preserva los permisos originales del archivo y emite un evento de recarga para refrescar los árboles de exploración.
* **Salidas:** Barra de progreso interactiva con porcentaje completado, archivo transferido íntegramente verificado contra su tamaño en bytes.
* **Excepciones:** Ante una desconexión abrupta de la red, la transferencia entrará en estado de reintento o pausa, preservando la porción transferida para reanudación si el servidor lo soporta.

#### RF-10: Apertura y Visualización Tridimensional de Archivos Cristalográficos (.cif)
* **Sintaxis Formal:** El sistema DEBERÁ parsear y generar una representación tridimensional interactiva de la celda unitaria y posiciones atómicas cuando el usuario abra un archivo con extensión `.cif`.
* **Entradas:** Contenido del archivo cristalográfico `.cif` (parámetros de red `_cell_length_a`, `b`, `c`, ángulos `_cell_angle_alpha`, `beta`, `gamma`, etiquetas `_atom_site_type_symbol`, coordenadas fraccionarias `_atom_site_fract_x`, `y`, `z`).
* **Procesamiento:**
  1. `Structure3DEditorProvider` captura la apertura del documento mediante la API `CustomTextEditorProvider`.
  2. Carga en el Webview el motor de renderizado 3D WebGL con aislamiento estricto de scripts mediante Content Security Policy (CSP).
  3. Parsea los bucles cristalográficos (`loop_`) transformando las coordenadas fraccionarias a coordenadas cartesianas ortogonales en Angstroms (\AA).
  4. Construye la geometría de la celda cristalina (paralelepípedo delimitador) y genera esferas coloreadas según la convención CPK para cada especie atómica.
  5. Si el usuario modifica el texto del archivo `.cif`, el webview recibe un mensaje reactivo (`type: 'update'`) y reconstruye la malla sin perder la posición de la cámara.
* **Salidas:** Panel de visualización 3D interactivo con rotación orbital, traslación, zoom y visualización de la celda unitaria.
* **Excepciones:** Si el archivo `.cif` presenta inconsistencias de sintaxis o campos incompletos, el visor mostrará un banner de diagnóstico con la línea exacta del error permitiendo conmutar a la vista de texto plano.

#### RF-11: Visualización Molecular 3D y Medición de Enlaces (.xyz)
* **Sintaxis Formal:** El sistema DEBERÁ interpretar las coordenadas moleculares cartesianas, renderizar los enlaces químicos y permitir la medición interactiva de distancias interatómicas cuando el usuario interactúe con un archivo `.xyz`.
* **Entradas:** Archivo de coordenadas `.xyz` (primera línea: número de átomos $N$; segunda línea: comentario; líneas subsecuentes: símbolo del elemento, coordenadas $x$, $y$, $z$).
* **Procesamiento:**
  1. El analizador lee la cabecera y el conjunto de $N$ átomos.
  2. Calcula la matriz de distancias euclidianas entre todos los pares de átomos $i, j$:
     $$d_{ij} = \sqrt{(x_i - x_j)^2 + (y_i - y_j)^2 + (z_i - z_j)^2}$$
  3. Genera cilindros de enlace (*bonds*) para aquellos pares cuya distancia cumpla el criterio de radio covalente estándar:
     $$d_{ij} \le 1.15 \times (r_{\text{cov}, i} + r_{\text{cov}, j})$$
  4. Habilita el modo de inspección métrica: al seleccionar dos átomos consecutivos mediante clic de ratón, calcula y superpone una línea de cota con la distancia exacta en Angstroms (\AA).
* **Salidas:** Vista tridimensional de la molécula con topología de enlaces visualizada y etiquetas flotantes de distancias atómicas.
* **Excepciones:** Si el número de átomos declarados no coincide con las filas de coordenadas provistas, el editor emitirá una advertencia semántica en el panel de problemas del IDE.

#### RF-12: Resaltado Sintáctico y Diagnóstico de Archivos Quantum ESPRESSO (.in, .out, .pwi, .pwo)
* **Sintaxis Formal:** El sistema DEBERÁ clasificar léxicamente y aplicar coloración sintáctica contextual a namelists, tarjetas de entrada y directivas de Quantum ESPRESSO cuando el usuario visualice archivos `.in`, `.pwi`, `.out` o `.pwo`.
* **Entradas:** Documento de texto correspondiente a entradas o salidas de Quantum ESPRESSO.
* **Procesamiento:**
  1. El motor TextMate del IDE aplica la gramática `syntaxes/quantum-espresso-input.tmLanguage.json` o `quantum-espresso-output.tmLanguage.json`.
  2. Identifica bloques de namelists estándar (`&CONTROL`, `&SYSTEM`, `&ELECTRONS`, `&IONS`, `&CELL`).
  3. Identifica y resalta tarjetas atómicas (`ATOMIC_SPECIES`, `ATOMIC_POSITIONS`, `K_POINTS`, `CELL_PARAMETERS`).
  4. En archivos de salida (`.out`, `.pwo`), resalta valores de convergencia de energía de Fermi, energía total scf (`! total energy = ... Ry`), presiones y mensajes de finalización ("JOB DONE.").
* **Salidas:** Resaltado de sintaxis enriquecido con soporte de plegado de código por bloques (*folding*) y concordancia de llaves.
* **Excepciones:** En caso de caracteres anómalos o codificación no UTF-8, el editor cargará el documento preservando los bytes en fallback con aviso de advertencia.

#### RF-13: Plantillas y Snippets Inteligentes para Cálculos SCF, Relax y Bandas
* **Sintaxis Formal:** El sistema DEBERÁ proporcionar fragmentos de código autocompletables con tab-stops parametrizados cuando el usuario escriba prefijos de simulación en un archivo de entrada Quantum ESPRESSO.
* **Entradas:** Disparadores de texto en el editor (`qe-scf`, `qe-relax`, `qe-bands`, `qe-vc-relax`).
* **Procesamiento:**
  1. El motor de snippets del lenguaje detecta la coincidencia del prefijo en el cursor.
  2. Expande la plantilla formal estructurada con valores recomendados por defecto (ej. `calculation = 'scf'`, `ecutwfc = 45.0`, `ecutrho = 360.0`, `conv_thr = 1.0d-8`).
  3. Posiciona secuencialmente el cursor sobre los parámetros que requieren definición del usuario (especies atómicas, pseudopotenciales y factores de celda).
* **Salidas:** Inyección limpia del bloque de configuración en el buffer del editor activo.
* **Excepciones:** Ninguna; si el snippet es cancelado con `Escape`, se restaura el texto previo sin efectos colaterales.

#### RF-14: Soporte Sintáctico y Directivas #SBATCH para Slurm (.slurm, .sbatch)
* **Sintaxis Formal:** El sistema DEBERÁ reconocer, validar sintácticamente y colorear las directivas del planificador Slurm cuando el usuario edite scripts de ejecución `.slurm` o `.sbatch`.
* **Entradas:** Líneas que inician con el prefijo `#SBATCH` seguidas de opciones de reserva de recursos (ej. `--job-name=`, `--nodes=`, `--ntasks-per-node=`, `--time=`, `--partition=`, `--mem=`).
* **Procesamiento:**
  1. La gramática `syntaxes/slurm.tmLanguage.json` evalúa las directivas Slurm diferenciándolas de comentarios estándar de Bash (`#`).
  2. Resalta argumentos clave y valores numéricos o cronológicos (formato `HH:MM:SS` o `D-HH:MM`).
  3. Ofrece sugerencias de completado automático a través de `snippets/slurm.code-snippets`.
* **Salidas:** Presentación visual distintiva de directivas de clúster con validación de opciones estándar.
* **Excepciones:** Si se suministra una opción obsoleta o desconocida, el parser de diagnóstico subraya la directiva con severidad informativa.

#### RF-15: Inspección de Pseudopotenciales UPF (.upf, .UPF)
* **Sintaxis Formal:** El sistema DEBERÁ analizar la cabecera XML de archivos de pseudopotenciales UPF y presentar sus metadatos físicos cuando el usuario abra archivos con extensión `.upf` o `.UPF`.
* **Entradas:** Archivo UPF en formato v1 (texto plano) o v2 (encapsulado XML).
* **Procesamiento:**
  1. La gramática de sintaxis y el analizador de metadatos leen la sección `<PP_HEADER>`.
  2. Extrae atributos clave: elemento químico (`element`), tipo de funcional de intercambio y correlación (`functional`), tipo de pseudopotencial (Norm-Conserving, Ultrasoft, PAW), radio de corte sugerido para función de onda (`wfc_cutoff`) y densidad (`rho_cutoff`), y carga de valencia ($Z_{\text{val}}$).
  3. Resalta la estructura de tablas de proyectores y potenciales locales/no-locales.
* **Salidas:** Coloración estructural y tarjeta informativa emergente (*hover*) con los parámetros físicos recomendados para el cálculo.
* **Excepciones:** Si el archivo UPF se encuentra corrupto o truncado, el sistema advertirá de la imposibilidad de validar los radios de corte sin bloquear la edición del archivo.

#### RF-16: Exposición del Servidor MCP stdio con 9 Herramientas Especializadas
* **Sintaxis Formal:** El sistema DEBERÁ ejecutar un servidor compatible con el protocolo Model Context Protocol (MCP) a través de los canales estándar de entrada y salida (`stdio`) exponiendo un registro oficial de 9 herramientas cuando sea invocado por clientes o agentes IA.
* **Entradas:** Flujo JSON-RPC 2.0 sobre stdin con métodos de handshake (`initialize`), listado de herramientas (`tools/list`) y ejecución (`tools/call`).
* **Procesamiento:**
  1. `mcp/server.py` y `mcp/tools.py` inician el bucle de eventos registrando exactamente las siguientes 9 herramientas:
     - `hpc_slurm_queue`: Consulta de trabajos en cola con filtros de usuario y estado.
     - `hpc_slurm_submit`: Encolamiento de scripts de cómputo en el clúster.
     - `hpc_slurm_cancel`: Aborto seguro de trabajos en ejecución o espera.
     - `hpc_slurm_log`: Lectura de bloques de registros de salida de simulaciones.
     - `hpc_validate_qe`: Validación semántica de sintaxis y consistencia de inputs Quantum ESPRESSO.
     - `hpc_inspect_structure`: Extracción de parámetros cristalográficos de archivos `.cif` y `.xyz`.
     - `hpc_list_clusters`: Inspección de la lista de clústeres configurados y sus perfiles de red.
     - `hpc_sftp_list`: Listado remoto de directorios mediante el subsistema SFTP.
     - `hpc_sftp_read`: Lectura remota segura de archivos de configuración o resultados.
  2. Valida los argumentos recibidos contra esquemas JSON estrictos (`ToolInputSchema`).
  3. Ejecuta el manejador asociado de forma síncrona/asíncrona y empaqueta el resultado en objetos `CallToolResult`.
* **Salidas:** Respuestas estructuradas JSON-RPC 2.0 en stdout con textos de respuesta (`TextContent`) o banderas de error normalizadas (`isError: true/false`).
* **Excepciones:** Solicitudes con argumentos inválidos o herramientas inexistentes retornarán errores formateados JSON-RPC con códigos de error estándar sin provocar la finalización del servidor.

#### RF-17: Delegación y Ejecución de Herramientas de Supercómputo mediante Agentes IA
* **Sintaxis Formal:** El sistema DEBERÁ interpretar las solicitudes formuladas en lenguaje natural por el usuario, resolver las herramientas MCP pertinentes y ejecutarlas en el entorno de supercómputo cuando se interactúe con el asistente inteligente.
* **Entradas:** Prompt en lenguaje natural del usuario solicitando operaciones de clúster (ej. "¿Cuáles de mis simulaciones están corriendo actualmente en Quantum Mobile y muéstrame las últimas líneas del log?").
* **Procesamiento:**
  1. El agente formula llamadas a herramientas (`tool_calls`) dirigidas al servidor MCP de HPC Studio (`hpc_slurm_queue`, `hpc_slurm_log`).
  2. El entorno valida la política de seguridad y permisos de ejecución de comandos sobre el clúster.
  3. Ejecuta las operaciones en el host remoto y retorna los datos tabulares procesados al modelo del agente.
* **Salidas:** Respuesta en el chat sintetizando el estado de las simulaciones, identificadores de trabajo y análisis del progreso de convergencia energética.
* **Excepciones:** Si la herramienta remota falla por tiempo de espera de red (timeout) o denegación de acceso, el agente recibirá el mensaje de error explícito y propondrá alternativas de mitigación al usuario.

#### RF-18: Integración de Antigravity como Proveedor Nativo en el Chat del IDE
* **Sintaxis Formal:** El sistema DEBERÁ integrar el ejecutable CLI de Google Antigravity (`agy`) como proveedor conversacional dentro de la interfaz del IDE cuando el usuario invoque el comando `hpc-studio.invokeAntigravityAgent` o interactúe en el panel de chat.
* **Entradas:** Comando de activación, prompt del usuario, identificador de sesión existente (`sessionId`), directorio de trabajo del proyecto.
* **Procesamiento:**
  1. `AntigravityAgentBridge` localiza el binario en la ruta configurada `hpc-studio.antigravityPath` o en `~/.local/bin/agy`.
  2. Genera un proceso hijo aislado con los argumentos:  
     `agy -p <prompt> --output-format json [--conversation <conversationId>]`.
  3. Lee los eventos de salida capturando el stream de razonamiento, invocaciones de herramientas y texto de respuesta final.
  4. Mantiene el mapa de identificadores de conversación activos para permitir diálogos multi-turno coherentes.
* **Salidas:** Flujo de texto interactivo con renderizado de Markdown, bloques ejecutables y control de cancelación de tarea.
* **Excepciones:** Si el binario `agy` no está instalado en el sistema, el puente interceptará el error `ENOENT` y desplegará una notificación guiada invitando a instalar el CLI de Antigravity o configurar su ruta manual en ajustes.

#### RF-19: Detección y Adaptación de Temas Visuales (Oscuro/Claro) del Sistema Operativo
* **Sintaxis Formal:** El sistema DEBERÁ escuchar los cambios de tema visual y sincronizar la paleta de colores del cliente VS Code, los visores 3D WebGL y los componentes de terminal cuando el usuario modifique la apariencia del sistema operativo o del editor.
* **Entradas:** Evento de cambio de tema del entorno (`window.onDidChangeActiveColorTheme`).
* **Procesamiento:**
  1. El sistema clasifica el tipo de tema activo en: Oscuro (`ColorThemeKind.Dark`), Claro (`ColorThemeKind.Light`) o Alto Contraste (`HighContrast`).
  2. Envía un mensaje de sincronización a los Webviews activos (`type: 'theme-changed', theme: 'dark' | 'light'`).
  3. Los visores 3D adaptan reactivamente el color de fondo de la escena WebGL (ej. gris oscuro `#1e1e1e` a blanco `#ffffff`), reajustando la intensidad de las luces ambientales y direccionales para asegurar legibilidad.
  4. Actualiza los colores semánticos de los iconos de la barra de estado y árboles de exploración.
* **Salidas:** Transición visual instantánea y fluida de toda la suite de interfaces sin parpadeos ni recarga forzada de los modelos moleculares.
* **Excepciones:** Ninguna; ante temas personalizados no estándar, el sistema recurrirá a la paleta estándar de alto contraste como salvaguarda ergonómica.

#### RF-20: Verificación de Seguridad y Autenticación con Token Bearer Dinámico
* **Sintaxis Formal:** El sistema DEBERÁ validar la presencia y validez del token criptográfico efímero de sesión en cada solicitud HTTP o conexión WebSocket entrante cuando un cliente intente interactuar con el backend sidecar.
* **Entradas:** Solicitudes entrantes al daemon FastAPI con cabeceras `X-HPC-Token`, `Authorization: Bearer <token>` o parámetros de consulta `?token=<token>`.
* **Procesamiento:**
  1. La dependencia de seguridad `TokenVerifier` intercepta la petición entrante antes de alcanzar los enrutadores de la API.
  2. Extrae el token mediante la función `extract_token_from_request`.
  3. Compara en tiempo constante (mediante `secrets.compare_digest`) el token recibido con el token de sesión generado al arranque por el `ServerConfig`.
  4. Si los tokens coinciden, permite el paso hacia el controlador del endpoint.
* **Salidas:** Acceso concedido a los recursos del sidecar.
* **Excepciones:** Si el token es ausente, inválido o difiere en longitud, el servidor rechazará de inmediato la solicitud respondiendo con código HTTP `401 Unauthorized` (`{"detail": "Invalid or missing HPC Studio authentication token"}`) o cerrando el socket WebSocket con código `1008 Policy Violation`.

---

### 3.3 Requisitos No Funcionales (RNF-01 a RNF-10) — Norma ISO/IEC 25010 (SQuaRE)

#### RNF-01 (Eficiencia de Desempeño - Latencia de Handshake):
* **Sintaxis Formal:** El sistema DEBERÁ completar el proceso completo de arranque del daemon sidecar, generación de credenciales criptográficas y confirmación de handshake IPC en un tiempo total inferior a **500 milisegundos** medido desde la activación de la extensión en un 95% de los inicios estándar.
* **Métrica:** $T_{\text{handshake}} \le 500\text{ ms}$ (Percentil P95).
* **Método de Verificación:** Prueba automatizada de integración y benchmarking con telemetría de timestamp.

#### RNF-02 (Eficiencia de Desempeño - Streaming de Logs en Tiempo Real):
* **Sintaxis Formal:** El sistema DEBERÁ procesar y emitir las líneas provenientes de archivos de registro remotos a través del WebSocket con una latencia de transmisión extremo a extremo inferior a **200 milisegundos** bajo un régimen de hasta 1,000 líneas emitidas por segundo.
* **Métrica:** $T_{\text{latencia\_log}} \le 200\text{ ms}$ con throughput continuo de 1,000 líneas/s.
* **Método de Verificación:** Prueba de estrés con inyección de logs masivos sobre conexión SSH loopback simulada.

#### RNF-03 (Seguridad - Permisos Restrictivos de Descriptores y Archivos en UNIX):
* **Sintaxis Formal:** El sistema DEBERÁ restringir los permisos de acceso de cualquier archivo de configuración, tokens de sesión temporales o llaves SSH generadas en el sistema de archivos local al modo octal estricto **0o600** (`-rw-------`), impidiendo lectura o escritura por usuarios ajenos al propietario del proceso.
* **Métrica:** Máscara de permisos de archivo verificada: `st_mode & 0o777 == 0o600`.
* **Método de Verificación:** Inspección de auditoría de seguridad y aserciones unitarias en `test_security_audit.py`.

#### RNF-04 (Seguridad - Aislamiento de Tokens y Credenciales en Memoria Volátil):
* **Sintaxis Formal:** El sistema DEBERÁ aislar los tokens de autorización Bearer de 256 bits y credenciales de autenticación en la memoria volátil del proceso, garantizando que nunca se persistan en archivos de log de disco, volcados de diagnóstico o repositorios git.
* **Métrica:** 0 ocurrencias de tokens o secretos en texto plano en archivos de registro (`grep -r` sobre directorios de logs y workspace).
* **Método de Verificación:** Auditoría estática de código y escaneo de fuga de secretos mediante pruebas de seguridad.

#### RNF-05 (Portabilidad y Compatibilidad Multiplataforma):
* **Sintaxis Formal:** El sistema DEBERÁ operar con idéntica fidelidad funcional y comportamiento determinista en sistemas operativos **GNU/Linux (x86_64, ARM64)**, **Microsoft Windows 10/11** y **Apple macOS (Intel y Apple Silicon)**.
* **Métrica:** 100% de la suite de pruebas unitarias y de integración superadas con éxito en los tres sistemas operativos en pipelines de CI/CD.
* **Método de Verificación:** Ejecución automatizada de matrices de prueba en GitHub Actions sobre imágenes Linux, Windows y macOS.

#### RNF-06 (Fiabilidad - Tolerancia a Fallos y Reconexión Automática):
* **Sintaxis Formal:** El sistema DEBERÁ recuperarse de interrupciones abruptas de red en canales SSH o cierres inesperados del proceso sidecar mediante una política de reconexión transparente y reintentos automáticos (máximo 5 reintentos con respaldo exponencial de hasta 10 segundos) sin congelar la interfaz de usuario ni provocar pérdida de buffers de edición activos.
* **Métrica:** Cero bloqueos de la UI (tasa de *Application Not Responding* = 0%) y reconexión exitosa tras restauración del socket en menos de 2 segundos.
* **Método de Verificación:** Prueba de inyección de fallos mediante corte forzado de sockets y terminación por `SIGKILL` del demonio.

#### RNF-07 (Usabilidad y Accesibilidad - Rendimiento del Visor 3D):
* **Sintaxis Formal:** El sistema DEBERÁ renderizar modelos moleculares y cristalográficos de hasta **50,000 átomos** manteniendo una tasa de cuadros por segundo no inferior a **60 FPS** durante operaciones de rotación interactiva y traslación en GPUs estándar con soporte WebGL 2.0.
* **Métrica:** Cuadros por segundo promedio $\ge 60\text{ FPS}$ en escenas de hasta 50,000 entidades atómicas.
* **Método de Verificación:** Prueba de rendimiento gráfico en navegador headless con instrumentación de Chrome DevTools / Playwright.

#### RNF-08 (Mantenibilidad y Modularidad del Código):
* **Sintaxis Formal:** El código base del sistema DEBERÁ estructurarse de manera modular y desacoplada, asegurando una cobertura de pruebas unitarias superior al **85%** en la capa de servicios backend Python y cumpliendo estrictamente con tipado estático completo (mypy en Python y strict mode en TypeScript).
* **Métrica:** Cobertura de pruebas $\ge 85\%$ reportada por `pytest-cov`, 0 errores de tipado bajo compiladores estrictos.
* **Método de Verificación:** Análisis estático automatizado con `mypy --strict` y reporte de cobertura con `pytest`.

#### RNF-09 (Compatibilidad de Estándares Científicos e Interoperabilidad):
* **Sintaxis Formal:** El sistema DEBERÁ adherirse estrictamente a las especificaciones formales de los formatos cristalográficos del IUCr (CIF Core Dictionary v2.x), formatos moleculares XYZ estándar, especificaciones de tarjetas Quantum ESPRESSO v7.x y especificaciones del Model Context Protocol (MCP 2024-11).
* **Métrica:** 100% de conformidad en pruebas de análisis sobre el banco oficial de archivos de prueba (`samples/` de Quantum ESPRESSO y base de datos COD/PDB).
* **Método de Verificación:** Pruebas funcionales de análisis comparativo frente a parsers de referencia (ASE / pymatgen).

#### RNF-10 (Eficiencia de Recursos y Concurrencia de Conexiones):
* **Sintaxis Formal:** El sistema DEBERÁ mantener un consumo de memoria en reposo (*idle*) para el demonio Python inferior a **80 MB** de memoria RSS y permitir la gestión concurrente de hasta **10 sesiones remotas simultáneas** de monitoreo y transferencia SFTP sin degradación medible del tiempo de respuesta del IDE.
* **Métrica:** Memoria RSS en reposo $< 80\text{ MB}$; tiempo de respuesta ante peticiones concurrentes P99 $< 50\text{ ms}$.
* **Método de Verificación:** Perfilado de memoria con herramientas de diagnóstico de procesos (`psutil`, `memory_profiler`).

---

## 4. Matriz de Trazabilidad Bidireccional

La siguiente matriz establece el mapeo bidireccional exhaustivo entre los Requisitos Funcionales (RF), los Casos de Uso (CU), los Componentes de Arquitectura del sistema y los Módulos de Pruebas Unitarias e Integración encargados de su validación y verificación:

| ID Requisito | Denominación del Requisito | Caso de Uso Asociado | Componentes de Arquitectura Responsables | Módulo de Pruebas Unitarias / QA | Estado de Verificación |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RF-01** | Ciclo de Vida del Sidecar | `CU-10` | `SidecarSupervisor` (TS), `server/app.py`, `server/cli.py` (Py) | `tests/test_server.py`, `test_state.py` | Verificado |
| **RF-02** | Conexiones SSH y ~/.ssh/config | `CU-01` | `ssh/config_parser.py`, `ssh/client.py`, `views/clustersView.ts` | `tests/test_ssh_config.py`, `test_ssh_client.py` | Verificado |
| **RF-03** | Preset Quantum Mobile | `CU-01` | `views/clustersView.ts` (`QUANTUM_MOBILE_PRESET`), `ssh/client.py` | `tests/test_ssh_client.py`, `test_ssh_tunnel.py` | Verificado |
| **RF-04** | Monitoreo Cola Slurm (squeue) | `CU-02` | `slurm/client.py`, `slurm/monitor.py`, `views/slurmQueueView.ts` | `tests/test_slurm_client.py`, `test_slurm_monitor.py` | Verificado |
| **RF-05** | Envío de Trabajos Slurm (sbatch) | `CU-03` | `slurm/client.py`, `slurm/generator.py`, `slurm/watchdog.py` | `tests/test_slurm_client.py`, `test_slurm_generator.py` | Verificado |
| **RF-06** | Cancelación de Trabajos (scancel)| `CU-02` | `slurm/client.py`, `views/slurmQueueView.ts` | `tests/test_slurm_client.py` | Verificado |
| **RF-07** | Streaming de Logs en Vivo | `CU-04` | `slurm/log_follower.py` (`RemoteLogStreamer`), `server/app.py` | `tests/test_slurm_log_follower.py` | Verificado |
| **RF-08** | Exploración Remota SFTP | `CU-07` | `sftp/client.py`, `views/sftpExplorerView.ts` | `tests/test_sftp_engine.py` | Verificado |
| **RF-09** | Transferencia Bidireccional SFTP| `CU-07` | `sftp/transfer_queue.py`, `sftp/client.py` | `tests/test_sftp_transfer.py` | Verificado |
| **RF-10** | Visor 3D Cristalográfico (.cif) | `CU-05` | `Structure3DEditorProvider` (TS), `media/structure3d/`, WebGL | `tests/test_crystallography_parsers.py` | Verificado |
| **RF-11** | Visor Molecular 3D y Métricas (.xyz)| `CU-06` | `Structure3DEditorProvider`, `crystallography/models.py` | `tests/test_crystallography_models.py` | Verificado |
| **RF-12** | Resaltado y Diagnóstico QE | `CU-03` | `syntaxes/quantum-espresso-*.json`, `qe/parser.py` | `tests/test_qe_input_engine.py`, `test_qe_output_parser.py` | Verificado |
| **RF-13** | Snippets Inteligentes QE | `CU-03` | `snippets/quantum-espresso-input.code-snippets` | `tests/test_qe_input_engine.py` | Verificado |
| **RF-14** | Soporte Sintáctico Slurm | `CU-03` | `syntaxes/slurm.tmLanguage.json`, `snippets/slurm.code-snippets` | `tests/test_slurm_generator.py` | Verificado |
| **RF-15** | Inspección Pseudopotenciales UPF | `CU-03` | `syntaxes/upf.tmLanguage.json`, `qe/validator.py` | `tests/test_qe_pseudos_and_kpath.py` | Verificado |
| **RF-16** | Servidor MCP stdio (9 Tools) | `CU-09` | `mcp/server.py`, `mcp/tools.py`, `mcp/cli.py` | `tests/test_mcp.py` | Verificado |
| **RF-17** | Delegación de Herramientas IA | `CU-09` | `mcp/tools.py`, `agent/bridge.py` | `tests/test_agent_tools.py`, `test_agent_tools_and_sandbox.py` | Verificado |
| **RF-18** | Integración Nativa Antigravity | `CU-08` | `agent/antigravityAgent.ts`, `agent/bridge.py` | `tests/test_agent_agy_provider.py`, `test_agent_providers.py` | Verificado |
| **RF-19** | Detección de Temas Visuales | Transversal | `Structure3DEditorProvider` (theme sync), VS Code Workbench | Inspección UI & Webview Theme Event Tests | Verificado |
| **RF-20** | Autenticación con Token Dinámico| `CU-10` | `server/auth.py` (`TokenVerifier`), `server/config.py` | `tests/test_server.py`, `test_security_audit.py` | Verificado |

---

## 5. Matriz de Verificación de Requisitos No Funcionales (ISO 25010)

| ID RNF | Dimensión ISO 25010 | Método de Verificación | Criterio de Aceptación Cuantitativo | Módulo / Herramienta de Validación |
| :--- | :--- | :--- | :--- | :--- |
| **RNF-01** | Eficiencia de Desempeño | Prueba Automatizada | Latencia de handshake $T \le 500\text{ ms}$ (P95) | `tests/test_server.py` |
| **RNF-02** | Eficiencia de Desempeño | Prueba de Carga / Streaming | Latencia de línea $T \le 200\text{ ms}$ a 1,000 líneas/s | `tests/test_slurm_log_follower.py` |
| **RNF-03** | Seguridad | Inspección y Análisis | Permisos de sockets y archivos = `0o600` | `tests/test_security_audit.py` |
| **RNF-04** | Seguridad | Análisis Estático / Auditoría | 0 credenciales o tokens filtrados en logs | `tests/test_security_audit_hardening.py` |
| **RNF-05** | Portabilidad | Demostración en CI/CD | 100% de suites verdes en Linux, Windows y macOS | GitHub Actions Workflow Multi-OS Matrix |
| **RNF-06** | Fiabilidad | Inyección de Fallos | Reconexión $< 2\text{ s}$ ante caída sin crasheo de UI | `tests/test_slurm_watchdog.py`, `test_server.py`|
| **RNF-07** | Usabilidad / Ergonomía | Demostración Gráfica | $\ge 60\text{ FPS}$ en escenas de hasta 50k átomos | Benchmark de renderizado WebGL en Chromium |
| **RNF-08** | Mantenibilidad | Análisis Estático | Cobertura $\ge 85\%$, 0 errores de tipado estricto | `pytest --cov=hpc_studio`, `mypy --strict` |
| **RNF-09** | Interoperabilidad | Prueba Funcional | 100% conformidad con CIF Core, UPF v2 y MCP 2024 | `tests/test_crystallography_parsers.py`, `test_mcp.py`|
| **RNF-10** | Eficiencia de Recursos | Perfilado de Memoria | RSS en reposo $< 80\text{ MB}$, concurrencia 10 hosts | Pruebas de estrés y benchmarking de recursos |

---

## 6. Apéndices: Suposiciones, Dependencias y Riesgos

### 6.1 Suposiciones del Entorno Operativo
1. Los clústeres remotos disponen de un servicio OpenSSH escuchando en los puertos configurados y permiten ejecución de comandos no interactivos a través del subsistema de shell.
2. La máquina virtual o contenedor Quantum Mobile tiene configurado el reenvío de puertos (*port forwarding*) del puerto guest 22 al puerto host 2222.
3. El usuario posee llaves criptográficas SSH válidas y autorizadas en el archivo `~/.ssh/authorized_keys` de las máquinas de destino.

### 6.2 Dependencias Tecnológicas Clave
* **Python Runtime:** Python 3.12+ con bibliotecas `fastapi`, `uvicorn`, `paramiko`, `pydantic`, `mcp`.
* **Entorno VS Code:** API de extensibilidad de Visual Studio Code 1.90.0 o superior.
* **Inteligencia Artificial:** Binario `agy` de Google Antigravity compatible con la especificación de comandos CLI v2.0.

### 6.3 Gestión de Riesgos Técnicos
* **Riesgo R-01 (Incompatibilidad de Directivas Slurm entre Versiones):** Variaciones en la salida de `squeue` entre Slurm v21 y v24.  
  *Mitigación:* Se implementa un formateador explícito con delimitador rígido (`--format="%i|%j|..."`), independizando el parseo de configuraciones regionales del clúster.
* **Riesgo R-02 (Cierre Inesperado de Túneles SSH por Inactividad):** Cortafuegos intermedios que cortan conexiones inactivas.  
  *Mitigación:* Se configuran paquetes de mantenimiento de conexión (*KeepAlive*) cada 30 segundos mediante el cliente SSH de Paramiko.
