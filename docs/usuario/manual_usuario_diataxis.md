# Manual de Usuario: HPC Studio

**Sistema:** HPC Studio  
**Versión de Plataforma:** v1.143.0 (Workbench Electron / VS Code OSS)  
**Versión de Backend:** v0.1.0 (Python Sidecar FastAPI)  
**Audiencia:** Físicos computacionales, químicos de materiales, operadores de supercómputo e investigadores cuánticos/AI.  
**Arquitectura de Documentación:** Framework Diátaxis (Tutorials, How-To Guides, Reference, Explanation).

---

## Estructura Diátaxis de este Manual

```text
               PRACTICAL CRAFT (Acción)
                       ▲
                       │
      Cuadrante 2:     │    Cuadrante 1:
      How-To Guides    │    Tutorials
   (Orientado a Tareas)│    (Orientado al Aprendizaje / FTUX)
                       │
ACQUISITION ───────────┼─────────── APPLICATION
OF SKILL               │            OF SKILL
                       │
      Cuadrante 3:     │    Cuadrante 4:
      Reference        │    Explanation
(Orientado a Info)     │    (Orientado a la Comprensión)
                       │
                       ▼
             THEORETICAL KNOWLEDGE (Reflexión)
```

---

# Cuadrante 1: Tutorials (Learning-Oriented / FTUX)

Los tutoriales guían al principiante paso a paso por una ruta dorada, garantizando resultados verificables e inmediatos sin sobrecarga cognitiva ni opciones divergentes.

---

### Tutorial 1: Primeros Pasos en HPC Studio

**Objetivo:** Instalar el entorno, iniciar el workbench, ubicar la Activity Bar y confirmar que el motor de cálculo Sidecar está enlazado y listo.

#### Requisitos Previos
* Linux x86_64 / macOS ARM64 o x86_64 / Windows WSL2.
* Python 3.10 o superior instalado con `uv` o `pip`.

#### Paso 1: Lanzar HPC Studio
Ejecute el binario empaquetado de HPC Studio o inicie el entorno de desarrollo:
```bash
./hpc-studio
```
Al cabo de 2 a 3 segundos, la ventana principal del Workbench se desplegará mostrando la pantalla de bienvenida.

#### Paso 2: Navegar por la Activity Bar
Ubique la barra lateral izquierda (Activity Bar). Identifique el icono de **HPC Studio** (un átomo entrelazado con nodos de supercómputo):
1. Haga clic en el icono de **HPC Studio** en la Activity Bar.
2. Observe cómo se despliega el contenedor de vistas primario con tres paneles dedicados:
   * **Remote Clusters & SSH:** Administrador de conexiones y perfiles de cómputo.
   * **Slurm Queue Monitor:** Visualizador en tiempo real de colas de trabajo y estado de nodos.
   * **Cluster File Transfer (SFTP):** Navegador de archivos bidireccional entre la máquina local y el clúster.

#### Paso 3: Verificar la Barra de Estado del Sidecar
Mire el extremo inferior derecho de la barra de estado (Status Bar):
1. Deberá ver un indicador con el texto: `$(server-process) HPC Backend: Online (Port: 8000)`.
2. Si hace clic sobre el indicador, se abrirá la consola de salida mostrando el handshake criptográfico:
   ```text
   [HPC-Studio] Sidecar process spawned with PID 18420.
   [HPC-Studio] Ephemeral security handshake successful.
   [HPC-Studio] Backend API ready at http://127.0.0.1:8000.
   ```
*(Resultado: El sistema se encuentra completamente inicializado y listo para ejecutar tareas).*

---

### Tutorial 2: Conexión y Configuración de Quantum Mobile en VirtualBox

**Objetivo:** Configurar una máquina virtual local de Quantum Mobile (con Quantum ESPRESSO y Slurm preinstalados) y conectarse con un solo clic desde HPC Studio.

#### Requisitos Previos
* Oracle VM VirtualBox 7.0+ instalado en su equipo host.
* Imagen de Quantum Mobile (`quantum-mobile-XX.XX.X.ova`) descargada desde [Materials Cloud](https://www.materialscloud.org/work/quantum-mobile).

#### Paso 1: Importar el OVA en VirtualBox
1. Abra Oracle VirtualBox.
2. Vaya al menú **Archivo > Importar servicio virtual...** (`Ctrl + I`).
3. Seleccione el archivo `quantum-mobile.ova` descargado y haga clic en **Siguiente**.
4. En la configuración de la máquina, asigne al menos **2 vCPUs** y **4096 MB de RAM**.
5. Haga clic en **Terminar** para completar la importación.

#### Paso 2: Configurar el Reenvío de Puertos (Port Forwarding)
Para que HPC Studio interactúe con el Slurm y SSH de la máquina virtual:
1. En VirtualBox, seleccione la máquina virtual **Quantum Mobile** (apagada).
2. Haga clic en **Configuración > Red > Adaptador 1** (asegúrese de que esté en modo **NAT**).
3. Despliegue **Avanzadas** y haga clic en el botón **Reenvío de puertos**.
4. Añada una regla con los siguientes parámetros exactos:
   * **Nombre:** `SSH_HPC_Studio`
   * **Protocolo:** `TCP`
   * **IP Anfitrión:** `127.0.0.1`
   * **Puerto Anfitrión:** `2222`
   * **IP Invitado:** *(dejar vacío)*
   * **Puerto Invitado:** `22`
5. Haga clic en **Aceptar** en ambas ventanas.
6. Encienda la máquina virtual haciendo clic en **Iniciar**. Espere a que cargue el escritorio o prompt de login de Quantum Mobile (`usuario: max`, `clave: max`).

#### Paso 3: Conectar desde HPC Studio con un Clic
1. En HPC Studio, abra la vista lateral de **HPC Studio**.
2. En la barra de título del panel **Remote Clusters & SSH**, haga clic en el icono **Connect to Quantum Mobile** (`$(vm)`).
3. El sistema reconocerá automáticamente la dirección `127.0.0.1:2222` con usuario `max` y contraseña `max`.
4. El indicador de estado del clúster cambiará inmediatamente a un círculo verde con la etiqueta:
   `Quantum Mobile (VirtualBox) - Connected (Latency: 0.8ms)`.
5. El panel **Slurm Queue Monitor** comenzará a refrescar la cola de trabajos de la máquina virtual automáticamente cada 3 segundos.

---

### Tutorial 3: Tu Primera Simulación Cuántica de Silicio (DFT-SCF)

**Objetivo:** Abrir una estructura cristalográfica de Silicio diamante, inspeccionarla en el visor interactivo 3D, generar un cálculo de auto-consistencia (SCF) de Quantum ESPRESSO, enviarlo a la cola Slurm y monitorear la convergencia.

#### Paso 1: Abrir e Inspeccionar la Estructura en 3D
1. En el Explorador de archivos (`Ctrl + Shift + E`), abra el directorio de muestras `samples/`.
2. Haga doble clic en el archivo `silicon_diamond.cif`.
3. HPC Studio abrirá automáticamente el **3D Structure Viewer**:
   * Observe la celda unitaria tridimensional con simetría cúbica centrada en las caras ($Fd\bar{3}m$).
   * Haga clic izquierdo y arrastre el cursor para rotar el cristal.
   * Con la rueda del ratón haga zoom hacia adelante y hacia atrás.
   * En la barra de herramientas del visor 3D, asegúrese de que el botón **Toggle Unit Cell** esté encendido para ver las líneas de contorno de la celda.

#### Paso 2: Generar y Validar la Plantilla SCF
1. En el explorador, abra `samples/silicon_scf.in`.
2. Observe el código con resaltado de sintaxis especializado para Quantum ESPRESSO:
   ```fortran
   &CONTROL
     calculation = 'scf',
     restart_mode = 'from_scratch',
     pseudo_dir = './',
     outdir = './tmp/',
     prefix = 'silicon'
   /
   &SYSTEM
     ibrav = 2,
     celldm(1) = 10.26,
     nat = 2,
     ntyp = 1,
     ecutwfc = 30.0
   /
   &ELECTRONS
     mixing_beta = 0.7,
     conv_thr = 1.0d-8
   /
   ATOMIC_SPECIES
     Si  28.086  Si.pbe-n-kjpaw_psl.1.0.0.UPF
   ATOMIC_POSITIONS (alat)
     Si 0.00 0.00 0.00
     Si 0.25 0.25 0.25
   K_POINTS (automatic)
     4 4 4 1 1 1
   ```
3. Presione `Ctrl + Shift + P` y ejecute: **HPC Studio: Validate Quantum ESPRESSO Input**.
4. En el panel inferior de **Problems**, compruebe que el validador emite: `0 Errors, 0 Warnings: Namelists and species validated successfully`.

#### Paso 3: Enviar el Trabajo a Slurm y Seguir el Log
1. Con el archivo `samples/silicon_scf.in` activo en el editor, abra la paleta de comandos (`Ctrl + Shift + P`) y seleccione:
   **HPC Studio: Submit Slurm Job (sbatch)**.
2. Ingrese el nombre del trabajo: `silicon_scf` y presione `Enter`.
3. Aparecerá una notificación en el margen inferior: `Job 101 submitted successfully to partition 'normal'`.
4. En el panel lateral **Slurm Queue Monitor**, verá el trabajo `101 (silicon_scf)` en estado **RUNNING** (`R`).
5. Haga clic derecho sobre el trabajo y seleccione **Stream Live Output (tail -f)**.
6. Se abrirá una pestaña de terminal integrada que mostrará el log en tiempo real:
   ```text
   iteration #  1 -- ecut =    30.00 Ry -- beta = 0.70
   Davidson diagonalization with overlap
   ethr =  1.00E-02,  ceps =   0.1245
   total energy              =     -15.82345021 Ry
   estimated scf accuracy    <       0.04321000 Ry

   iteration #  5 -- ecut =    30.00 Ry -- beta = 0.70
   total energy              =     -15.84562011 Ry
   estimated scf accuracy    <       0.00000004 Ry

   End of self-consistent calculation
   JOB DONE.
   ```
7. En el monitor de Slurm, el estado pasará a **COMPLETED** (`CD`).

---

# Cuadrante 2: How-To Guides (Task-Oriented por Roles)

Recetas orientadas a la resolución de problemas específicos. Se asume conocimiento básico del sistema.

---

## Rol 1: Físico / Químico de Materiales

### Cómo interactuar con cristales y moléculas (.cif / .xyz) en el Visor 3D

1. **Abrir el visor:**
   * Haga clic derecho sobre cualquier archivo `.cif` o `.xyz` en el explorador y seleccione **HPC Studio: Open in 3D Structure Viewer**.
   * Para trabajar en paralelo con el código, seleccione **HPC Studio: Open 3D View to the Side** (`Ctrl + K, V`).
2. **Controles de cámara:**
   * **Rotación:** Mantenga presionado el botón izquierdo del ratón y arrastre.
   * **Panorámica (Pan):** Mantenga presionado el botón derecho del ratón (o botón central) y desplace el cursor.
   * **Zoom:** Rueda del ratón o gesto de pellizco en el trackpad.
3. **Alternar visualización de enlaces y celda:**
   * Presione la tecla `B` en el visor para ocultar o revelar los cilindros de enlace covalente.
   * Presione la tecla `U` para alternar la jaula de vectores de la celda unitaria ($\mathbf{a}, \mathbf{b}, \mathbf{c}$).

### Cómo medir distancias interatómicas exactas

1. En la ventana activa del **3D Structure Viewer**, haga clic sobre el primer átomo objetivo. El átomo se iluminará con un halo de selección amarillo.
2. Mantenga presionada la tecla `Shift` y haga clic sobre el segundo átomo.
3. Se trazará una línea segmentada de calibración entre ambos centros atómicos y aparecerá una etiqueta flotante:
   ```text
   Distance [Si(1) - Si(2)]: 2.351 Å
   ```
4. Para cancelar la selección, haga clic en cualquier espacio vacío del lienzo 3D o presione `Escape`.

### Cómo generar y validar archivos de entrada para Quantum ESPRESSO

1. Cree un nuevo archivo con extensión `.in` o `.pwi`.
2. Escriba el prefijo `qe-scf` y presione `Tab` para expandir el snippet estándar con las namelists requeridas:
   * `&CONTROL`: Define `calculation` (`'scf'`, `'relax'`, `'bands'`), rutas de trabajo (`pseudo_dir`, `outdir`) y prefijo de salida.
   * `&SYSTEM`: Define geometría (`ibrav`, `celldm` o parámetros de red), número de átomos (`nat`), número de especies (`ntyp`) y corte de energía de ondas planas (`ecutwfc`).
   * `&ELECTRONS`: Define algoritmo de mezclado (`mixing_beta`) y umbral de convergencia (`conv_thr`).
3. Para validar que los pseudopotenciales coincidan con los elementos declarados:
   * Abra la paleta (`Ctrl + Shift + P`) y ejecute **HPC Studio: Validate Quantum ESPRESSO Input**.
   * El validador comprobará que los archivos `.UPF` referenciados existan en `pseudo_dir` y que `ecutwfc` sea adecuado para el tipo de pseudopotencial (Norm-Conserving vs. Ultrasoft/PAW).

---

## Rol 2: Ingeniero / Operador de Supercómputo

### Cómo dar de alta un clúster remoto vía SSH o usar perfiles de ~/.ssh/config

1. **Uso de configuración existente:**
   * HPC Studio detecta de forma transparente las entradas existentes en su archivo `~/.ssh/config`.
   * En el panel **Remote Clusters & SSH**, haga clic en el botón **Refresh Clusters** (`$(refresh)`). Todos los hostnames, usuarios y puertos se cargarán automáticamente en el árbol.
2. **Agregar un nuevo clúster manualmente:**
   * En la barra de título del panel, presione **Add Cluster Profile** (`$(add)`).
   * Complete el formulario interactivo:
     * **Cluster Name:** `Marenostrum-5`
     * **Hostname:** `mn1.bsc.es`
     * **Username:** `bscuser21`
     * **Port:** `22`
     * **Identity File:** `~/.ssh/id_ed25519_bsc`
     * **ProxyJump (Opcional):** `bastion.bsc.es:22`
   * Presione **Save & Connect**. La configuración se persistirá de forma segura en `hpc-studio.clusters` dentro de sus settings de usuario.

### Cómo monitorear la cola Slurm, cancelar jobs (scancel) y seguir logs en vivo

1. **Monitoreo dinámico:**
   * En el panel **Slurm Queue Monitor**, visualice la lista de trabajos agrupados por partición.
   * Los estados se codifican por colores normalizados:
     * Verde: `RUNNING (R)`
     * Amarillo: `PENDING (PD)`
     * Rojo: `FAILED (F)` / `NODE_FAIL (NF)`
     * Azul: `COMPLETED (CD)`
2. **Cancelar un trabajo:**
   * Pase el cursor sobre el trabajo problemático en el árbol de Slurm.
   * Haga clic en el botón de acción rápida **Cancel Job (scancel)** (`$(stop-circle)`).
   * Confirme el diálogo de seguridad con la tecla `Enter`. Se enviará inmediatamente la señal `SIGTERM` (o `SIGKILL` forzado si se mantiene presionado `Alt`).
3. **Streaming de salida (Tail en vivo):**
   * Haga clic derecho sobre cualquier trabajo activo y elija **Stream Live Output (tail -f)**.
   * Se iniciará una conexión multiplexada que emitirá el flujo incremental de líneas en una terminal dedicada, actualizándose a medida que el solver científico escribe en disco.

### Cómo transferir archivos y datasets masivos mediante el explorador SFTP

1. Despliegue el panel **Cluster File Transfer (SFTP)** en la vista lateral.
2. Navegue por la estructura de directorios del sistema de archivos remoto (`/home`, `/scratch`, `/gpfs/projects`).
3. **Para subir archivos locales:**
   * Arrastre cualquier archivo o carpeta desde el explorador local de VS Code y suéltelo sobre una carpeta en el árbol remoto de SFTP.
   * Alternativamente, haga clic en el icono **Upload Local File** (`$(cloud-upload)`).
4. **Para descargar resultados de cálculo:**
   * Haga clic derecho sobre el archivo remoto (por ejemplo, `silicon.save.tar.gz` o `output.pwo`) y presione **Download Remote File** (`$(cloud-download)`).
   * Seleccione el directorio destino local. Una barra de progreso en la Status Bar indicará velocidad de transferencia (MB/s) y tiempo estimado de llegada (ETA).

---

## Rol 3: Investigador Cuántico / AI Engineer

### Cómo utilizar el asistente Antigravity en el chat nativo para diagnosticar fallos de convergencia

1. Abra el panel de Chat nativo de VS Code / Antigravity (`Ctrl + Alt + I` o `Ctrl + Shift + P > HPC Studio: Invoke Antigravity Agent`).
2. Si un cálculo DFT falló o no converge tras 100 iteraciones, invoque al agente contextual:
   ```text
   @hpc Revisa el log de silicon_scf.out. La auto-consistencia no converge y oscila drásticamente en la energía. ¿Qué parámetros de mezclado recomiendas modificar en el archivo de entrada?
   ```
3. El agente de IA consultará las herramientas MCP integradas (`hpc_slurm_log` y `hpc_validate_qe`), leerá las últimas iteraciones y devolverá una recomendación cuantitativa:
   ```markdown
   He diagnosticado el cálculo de Silicio (Job ID 101):
   - La oscilación de energía entre iteraciones se debe a un `mixing_beta` demasiado agresivo (0.70).
   - Para sistemas con bandas semiconductoras o gaps pequeños, reduzca el mezclado:
     `mixing_beta = 0.3`
   - Modifique el modo de mezclado en `&ELECTRONS`:
     `mixing_mode = 'plain'`
     `diagonalization = 'david'`
   ```
4. Haga clic en el botón **Apply Fix** del bloque sugerido para actualizar directamente su archivo `.in`.

### Cómo solicitar la optimización de scripts batch para nodos GPU o particiones multinodo

1. Abra el script de envío de Slurm (`run_qe.slurm`).
2. En el chat con el agente Antigravity, solicite la adaptación para un clúster con aceleradores NVIDIA A100:
   ```text
   @hpc Optimiza este script de Slurm para ejecutarse en una partición con 4 GPUs A100 y 64 cores por nodo utilizando mpirun y aceleración CUDA de Quantum ESPRESSO 7.x.
   ```
3. El agente emitirá las directivas SBATCH precisas y variables de entorno de MPI/OpenMP:
   ```bash
   #!/bin/bash
   #SBATCH --job-name=qe_gpu_a100
   #SBATCH --partition=gpu
   #SBATCH --nodes=1
   #SBATCH --ntasks-per-node=4
   #SBATCH --cpus-per-task=16
   #SBATCH --gres=gpu:a100:4
   #SBATCH --time=04:00:00

   export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
   export OMP_PLACES=cores
   export OMP_PROC_BIND=close

   mpirun -np $SLURM_NTASKS pw.x -input silicon_scf.in > silicon_scf.out
   ```

---

# Cuadrante 3: Reference (Information-Oriented)

Especificación rigurosa, completa y neutral de los componentes, extensiones, comandos y configuraciones.

---

### Extensiones de Archivo y Lenguajes Soportados

| Extensión | Language ID | Descripción / Ámbito | Gramática / Resaltado |
| :--- | :--- | :--- | :--- |
| `.in`, `.pwi` | `quantum-espresso-input` | Archivo de entrada de cálculo para Quantum ESPRESSO (`pw.x`, `ph.x`). | Namelists (`&CONTROL`, etc.), tarjetas (`ATOMIC_POSITIONS`), unidades y flags. |
| `.out`, `.pwo` | `quantum-espresso-output` | Archivo de registro y salida estándar de Quantum ESPRESSO. | Reconocimiento de iteraciones SCF, bandas de energía, fuerzas y marcas de convergencia. |
| `.slurm`, `.sbatch` | `slurm` | Scripts de ejecución por lotes para el gestor Slurm Workload Manager. | Directivas `#SBATCH`, variables de entorno Slurm (`$SLURM_*`) y comandos shell. |
| `.cif` | `cif` | Formato estandarizado Crystallographic Information File (IUCr). | Etiquetas data/loop, parámetros de red, grupos espaciales y coordenadas fraccionarias. |
| `.xyz` | `xyz` | Coordenadas cartesianas moleculares estándar. | Conteo de átomos en cabecera, comentarios y columnas elementales $(x, y, z)$. |
| `.upf`, `.UPF` | `upf` | Formato Unified Pseudopotential Format para cálculo DFT. | Cabeceras XML/UPF, tipos de funcionales de intercambio-correlación y mallas radiales. |

---

### Catálogo de Comandos y Atajos de Teclado

| Identificador de Comando | Título en la Paleta de Comandos | Atajo de Teclado por Defecto | Contexto de Activación (`when`) |
| :--- | :--- | :--- | :--- |
| `hpc-studio.startSidecar` | `HPC Studio: Start Backend Server` | — | Siempre disponible |
| `hpc-studio.stopSidecar` | `HPC Studio: Stop Backend Server` | — | Backend en ejecución |
| `hpc-studio.restartSidecar` | `HPC Studio: Restart Backend Server` | — | Siempre disponible |
| `hpc-studio.checkStatus` | `HPC Studio: Show Backend Status` | — | Siempre disponible |
| `hpc-studio.invokeAntigravityAgent` | `HPC Studio: Invoke Antigravity Agent` | `Ctrl + Alt + I` | Siempre disponible |
| `hpc-studio.openIn3DViewer` | `HPC Studio: Open in 3D Structure Viewer` | `Alt + 3` | `resourceExtname in ['.cif', '.xyz']` |
| `hpc-studio.open3DSideBySide` | `HPC Studio: Open 3D View to the Side` | `Ctrl + K, V` | `resourceExtname in ['.cif', '.xyz']` |
| `hpc-studio.reopenAsText` | `HPC Studio: Reopen as Text` | `Alt + T` | `activeCustomEditorId == 'hpc-studio.structure3dViewer'` |
| `hpc-studio.refreshClusters` | `HPC Studio: Refresh Clusters` | — | Vista de clusters activa |
| `hpc-studio.connectClusterTerminal`| `HPC Studio: Connect SSH Terminal` | — | Nodo de cluster seleccionado |
| `hpc-studio.pingCluster` | `HPC Studio: Ping Cluster Latency` | — | Nodo de cluster seleccionado |
| `hpc-studio.addCluster` | `HPC Studio: Add Cluster Profile` | — | Siempre disponible |
| `hpc-studio.addQuantumMobile` | `HPC Studio: Connect to Quantum Mobile`| — | Siempre disponible |
| `hpc-studio.quantumMobileGuide` | `HPC Studio: Open Quantum Mobile Guide`| — | Siempre disponible |
| `hpc-studio.openTunnel` | `HPC Studio: Open SSH Tunnel` | — | Cluster seleccionado |
| `hpc-studio.refreshSlurmQueue` | `HPC Studio: Refresh Slurm Queue` | `Ctrl + Shift + R` | Vista de Slurm activa |
| `hpc-studio.submitJob` | `HPC Studio: Submit Slurm Job (sbatch)`| `Alt + S` | Script Slurm o QE activo |
| `hpc-studio.cancelJob` | `HPC Studio: Cancel Job (scancel)` | `Alt + C` | Trabajo Slurm seleccionado |
| `hpc-studio.followJobLog` | `HPC Studio: Stream Live Output (tail -f)`| `Alt + L` | Trabajo Slurm seleccionado |
| `hpc-studio.refreshSftp` | `HPC Studio: Refresh Remote Files` | — | Vista SFTP activa |
| `hpc-studio.uploadFile` | `HPC Studio: Upload Local File` | — | Directorio SFTP activo |
| `hpc-studio.downloadFile` | `HPC Studio: Download Remote File` | — | Archivo SFTP seleccionado |

---

### Parámetros de Configuración del IDE (`settings.json`)

| Parámetro | Tipo | Valor por Defecto | Descripción Técnica |
| :--- | :--- | :--- | :--- |
| `hpc-studio.pythonPath` | `string` | `""` | Ruta absoluta al binario intérprete de Python. Si está vacío, auto-detecta `.venv` o el PATH global. |
| `hpc-studio.autoStartSidecar` | `boolean`| `true` | Determina si el proceso sidecar de backend arranca automáticamente al iniciar el IDE. |
| `hpc-studio.serverHost` | `string` | `"127.0.0.1"` | Dirección IP en la que el backend FastAPI escucha peticiones HTTP y SSE. |
| `hpc-studio.serverPort` | `number` | `0` | Puerto TCP del backend. Si se define `0`, se asigna un puerto dinámico libre en el sistema. |
| `hpc-studio.logLevel` | `string` | `"info"` | Nivel de registro para la consola del backend (`debug`, `info`, `warning`, `error`). |
| `hpc-studio.antigravityPath` | `string` | `""` | Ruta al binario ejecutable de Antigravity CLI (`agy`). Si está vacío, se busca en `~/.local/bin/agy`. |
| `hpc-studio.clusters` | `array` | `[]` | Lista de perfiles de clusters configurados manualmente (nombre, host, usuario, puerto, key). |

---

### Variables de Entorno del Servidor Backend

| Variable de Entorno | Tipo | Valor por Defecto | Propósito / Efecto en Ejecución |
| :--- | :--- | :--- | :--- |
| `HPC_STUDIO_HOST` | `string` | `"127.0.0.1"` | Sobrescribe la interfaz de red a enlazar por el servidor Uvicorn. |
| `HPC_STUDIO_PORT` | `integer`| `8000` | Sobrescribe el puerto de escucha por defecto del backend. |
| `HPC_STUDIO_TOKEN` | `string` | *(Generado aleatoriamente)*| Token de seguridad Bearer para autenticar el canal de comunicación inter-proceso. |
| `HPC_STUDIO_WORKSPACE` | `string` | `.` (Directorio actual) | Ruta de trabajo raíz para resolución de scripts y transferencia local de archivos. |
| `HPC_STUDIO_DEBUG` | `boolean`| `false` | Activa recarga en caliente de código y expone la documentación OpenAPI en `/docs`. |

---

### Matriz de Errores y Diagnóstico (Troubleshooting)

| Código / Síntoma | Diagnóstico de Causa Raíz | Procedimiento de Resolución |
| :--- | :--- | :--- |
| `ERR_SIDECAR_HANDSHAKE_TIMEOUT` | El proceso Python no respondió en el puerto esperado durante los primeros 10 segundos tras el spawn. | 1. Verifique que Python 3.10+ esté instalado y disponible en PATH.<br>2. Ejecute `python -m hpc_studio.server.cli --debug` manualmente en una terminal para inspeccionar trazas de dependencias faltantes.<br>3. Ajuste `hpc-studio.pythonPath` en Settings apuntando al binario correcto de su entorno virtual. |
| `ERR_SSH_CONNECTION_REFUSED` | El clúster o la máquina virtual rechazaron la conexión en el puerto TCP especificado (ej. 22 o 2222). | 1. Si usa Quantum Mobile, verifique que la máquina virtual esté encendida en VirtualBox.<br>2. Verifique la regla de reenvío de puertos NAT (Host: `127.0.0.1:2222` -> Guest: `22`).<br>3. Ejecute `hpc-studio.pingCluster` desde la paleta de comandos para medir la latencia del socket TCP. |
| `ERR_SLURM_SBATCH_REJECTED` | La directiva de partición, tiempo o límite de memoria no es aceptada por el controlador `slurmctld`. | 1. Abra el script `.slurm` y revise las directivas `#SBATCH -p` y `#SBATCH --time`.<br>2. En la vista **Slurm Queue Monitor**, verifique los nombres exactos de partición disponibles en el clúster activo.<br>3. Consulte los detalles del error devueltos en la notificación emergente de HPC Studio. |
| `ERR_QE_PSEUDO_NOT_FOUND` | La tarjeta `ATOMIC_SPECIES` referencia un archivo `.UPF` que no existe en el directorio `pseudo_dir`. | 1. Descargue el pseudopotencial necesario (ej. desde el repositorio SSSP de Materials Cloud).<br>2. Colóquelo en el directorio relativo indicado en la namelist `&CONTROL pseudo_dir = './'` o use una ruta absoluta en el clúster. |
| `ERR_SFTP_PERMISSION_DENIED` | El usuario SSH no tiene permisos de lectura o escritura en el directorio remoto seleccionado. | 1. Compruebe los permisos del directorio remoto en la columna de permisos de la vista SFTP (ej. `drwxr-xr-x`).<br>2. Si escribe en sistemas de archivos paralelos (Lustre/GPFS), asegúrese de utilizar el directorio `/scratch/` o su área de proyecto autorizada. |

---

# Cuadrante 4: Explanation (Understanding-Oriented)

Discusión arquitectónica sobre los fundamentos y decisiones de diseño del sistema.

---

### ¿Por qué un Modelo Sidecar Desacoplado?

HPC Studio adopta el patrón arquitectónico **Sidecar** desacoplando la interfaz de usuario (desarrollada sobre la base de Electron y VS Code OSS) del motor de computación científica (implementado como un servicio Python de alto rendimiento en FastAPI).

```text
┌──────────────────────────────────────────────┐
│  HPC Studio Workbench (Electron / TS)        │
│  - 3D Structure Viewer (WebGL)               │
│  - Text Editors & QE Language Grammar        │
│  - Slurm Monitor & SFTP File Tree            │
└──────────────────────┬───────────────────────┘
                       │ HTTP / REST & Server-Sent Events (SSE)
                       │ (Handshake con Token Ephemeral Bearer)
┌──────────────────────▼───────────────────────┐
│  HPC Studio Sidecar Engine (Python FastAPI)  │
│  - Paramiko SSH / SFTP Multiplexing          │
│  - Slurm Engine Client & Log Streamer        │
│  - Crystallographic & QE Parsing Engines     │
│  - Model Context Protocol (MCP) Server       │
└──────────────────────────────────────────────┘
```

#### Ventajas Fundamentales del Desacoplamiento:
1. **Rendimiento de la Interfaz:** La manipulación de estructuras cristalográficas complejas y el renderizado 3D en WebGL requieren que el hilo principal de la interfaz esté completamente libre de bloqueos I/O causados por operaciones de red remotas (como transferencias SFTP o consultas SSH a clústeres lejanos).
2. **Acceso al Ecosistema Científico Nativo:** Python es el estándar de facto en computación cuántica, química computacional y modelado de materiales (ASE, Pymatgen, Spglib, QCEngine). El sidecar permite ejecutar estos algoritmos directamente sin la sobrecarga ni las limitaciones de puentes JavaScript-to-C++.
3. **Resiliencia y Ciclo de Vida:** Si la interfaz gráfica se recarga o experimenta una falla de renderizado, las tareas de fondo del sidecar (como el streaming de logs o colas de transferencia de archivos pesados) continúan en ejecución de forma ininterrumpida.

---

### Fundamentos del Handshake Criptográfico y Seguridad de Procesos Locales

Al iniciarse el Workbench de HPC Studio, el proceso Electron genera de forma dinámica un token de entropía criptográfica alta utilizando `crypto.randomBytes(32)` y lo inyecta como argumento o variable de entorno al invocar el subproceso Python:

$$\text{Token} \leftarrow \text{Base64Url}(\text{PRNG}_{256\text{ bits}})$$

#### Principios de Seguridad Implementados:
* **Enlace Exclusivo a Loopback:** El servidor FastAPI se enlaza estrictamente a `127.0.0.1`, impidiendo cualquier intento de conexión desde interfaces de red externas o máquinas remotas en la misma red local.
* **Verificación Bearer Estricta:** Cada invocación HTTP o conexión SSE debe incluir la cabecera `Authorization: Bearer <TOKEN>`. Peticiones no autorizadas son rechazadas de inmediato con un código `401 Unauthorized` de tiempo constante para evitar ataques de temporización.
* **Aislamiento Multi-Usuario en Sistemas Compartidos:** En servidores Linux multi-usuario donde varios investigadores comparten el mismo sistema operativo, otros usuarios locales no pueden inspeccionar ni invocar la API del backend sin poseer el token de sesión efímero, el cual nunca se persiste en disco plano.

---

### Simulación Híbrida HPC-QC y Portabilidad con Quantum Mobile

La investigación en ciencia de materiales moderna depende cada vez más de flujos de trabajo heterogéneos que combinan simulaciones clásicas de primeros principios (Density Functional Theory - DFT) con algoritmos de información cuántica (VQE, QAOA) ejecutados en clústeres híbridos.

#### El Rol de Quantum Mobile en HPC Studio
Para resolver la dificultad histórica de instalar herramientas científicas como Quantum ESPRESSO, Yambo, Wannier90 y el gestor Slurm en estaciones de trabajo locales (especialmente en entornos Windows o macOS con dependencias complejas de Fortran y OpenMPI), HPC Studio se integra nativamente con la máquina virtual **Quantum Mobile**:
* **Paridad Absoluta de Entorno:** Un cálculo configurado y probado en Quantum Mobile dentro de una laptop corre bajo exactamente el mismo gestor Slurm y las mismas versiones de librerías científicas que se utilizarán en supercomputadores de clase Petascale (como MareNostrum, Leonardo o Perlmutter).
* **Desarrollo Desconectado:** Los investigadores pueden diseñar sus pipelines de cálculo, verificar la sintaxis de sus archivos de entrada y comprobar el comportamiento de Slurm sin requerir conexión a internet ni consumir cuotas de cómputo en clústeres institucionales.
* **Transición Transparente:** Cambiar el destino de ejecución de la máquina virtual local a un supercomputador en producción requiere únicamente seleccionar otro nodo en el menú desplegable de clústeres de HPC Studio, sin necesidad de reescribir scripts ni alterar la estructura de datos del proyecto.
