# **HPC Studio Linux — Informe de Auditoría de Seguridad**
## **Auditoría Integral de Código, Lógica y Protocolos (Fase 1)**

**Estándar Aplicado:** `security-audit` skill (OWASP / CWE / Defensive Source-First Verification)  
**Fecha de Ejecución:** Octubre 2026  
**Alcance:** Fase 1 Completa (`src/hpc_studio/core/`, `src/hpc_studio/ssh/`, `src/hpc_studio/sftp/`, `src/hpc_studio/terminal/`, `src/hpc_studio/ui/`)  
**Resultado de Verificación:** **207 pruebas unitarias, de integración y de seguridad superadas al 100% (0 fallos, 0 regresiones)**

---

## 📌 1. Resumen Ejecutivo
Se ejecutó una auditoría de seguridad exhaustiva sobre todos los módulos desarrollados en la **Fase 1** de **HPC Studio Linux**. Dos agentes especializados evaluaron de forma independiente los límites de confianza (*trust boundaries*), vectores de inyección, manejo de credenciales en memoria, control de subprocesos y canales de comunicación remota.

Se identificaron y mitigaron **18 vectores de riesgo y debilidades de robustez** distribuidos en dos grandes frentes:
1. **Core, SSH y SFTP:** Path Traversal en descargas SFTP, sobreescritura de enlaces simbólicos, inyección en ProxyCommand, saneamiento de claves OpenSSH y protección de secretos en memoria volátil (**RNF-03**).
2. **Terminal, PTY, Subprocesos y UI:** Inyección y spoofing de secuencias ANSI/OSC, protección contra DoS por desbordamiento de búfer, aislamiento de descriptores de archivo (`FD_CLOEXEC`), recolección de procesos huérfanos/zombies, saneamiento de portapapeles y validación de Drag & Drop cruzado.

Todos los hallazgos fueron remediados mediante parches de código mínimos y efectivos, respaldados por **39 pruebas específicas de seguridad automatizadas** en [`tests/test_security_core_ssh.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/tests/test_security_core_ssh.py) y [`tests/test_security_terminal_ui.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/tests/test_security_terminal_ui.py).

---

## 🛡️ 2. Matriz de Hallazgos y Remediaciones

| ID | Subsistema | Tipo / Vulnerabilidad (CWE) | Severidad | Estado |
| :--- | :--- | :--- | :---: | :---: |
| **VULN-SFTP-01** | `sftp` | **Remote Path Traversal en Descargas** (CWE-22 / CWE-23): Servidor SFTP remoto malicioso enviando `../../` en nombres de archivo para escribir fuera del directorio destino local. | **HIGH** | ✅ Mitigado |
| **VULN-UI-01** | `ui/docks` | **Exfiltración Involuntaria de Archivos en Drag & Drop** (CWE-20 / CWE-200): Aceptación de texto plano en drop que encolaba archivos sensibles (`/etc/passwd`, `~/.ssh/id_rsa`). | **HIGH** | ✅ Mitigado |
| **VULN-TERM-01** | `terminal` | **Inyección de Secuencias ANSI/OSC y Buffer DoS** (CWE-150 / CWE-400): Títulos OSC no saneados con caracteres de control, buffers CSI/OSC sin límite y desbordamiento de memoria. | **HIGH** | ✅ Mitigado |
| **VULN-SFTP-02** | `sftp` | **Symlink Overwrite / Hijacking** (CWE-59): Descarga sobre enlace simbólico local existente provocaba sobreescritura del archivo apuntado por el symlink. | **MEDIUM** | ✅ Mitigado |
| **VULN-SSH-01** | `ssh` | **Inyección de Comandos en ProxyCommand** (CWE-78): Expansión de tokens `%h`, `%p`, `%r` con metacaracteres shell sin entrecomillado seguro. | **MEDIUM** | ✅ Mitigado |
| **VULN-CORE-01** | `core` | **Ataques de Enlace Simbólico y TOCTOU en Config/State** (CWE-59 / CWE-377): Lectura y guardado de configuraciones sobre symlinks preexistentes. | **MEDIUM** | ✅ Mitigado |
| **VULN-TERM-02** | `terminal` | **Fuga de Descriptores de Archivo PTY (`FD_CLOEXEC` ausente)** (CWE-403): El descriptor maestro PTY se heredaba a subprocesos hijos no relacionados. | **MEDIUM** | ✅ Mitigado |
| **VULN-TERM-03** | `terminal` | **Procesos Huérfanos y Zombies tras Cierre de Terminal** (CWE-400 / CWE-775): Terminación de shell sin propagar `SIGHUP`/`SIGKILL` a todo el grupo de procesos (`pgid`). | **MEDIUM** | ✅ Mitigado |
| **VULN-TERM-04** | `terminal` | **Resolución Insegura de `$SHELL`** (CWE-426): Ejecución de ejecutables relativos o no válidos especificados en la variable `$SHELL`. | **MEDIUM** | ✅ Mitigado |
| **VULN-UI-02** | `ui/widgets` | **Inyección de Comandos en Terminal vía Portapapeles** (CWE-150 / CWE-78): Pegado de secuencias ANSI ocultas, bytes nulos y textos arbitrariamente gigantes. | **MEDIUM** | ✅ Mitigado |
| **HARD-SSH-01** | `ssh` | **Path Traversal en `IdentityFile`** (CWE-22): Rutas relativas que escapaban de la carpeta `~/.ssh/`. | **LOW** | ✅ Mitigado |
| **HARD-SSH-02** | `ssh` | **Fuga de Descriptores en Paramiko Channel** (CWE-775): Omisión de cierre explícito de streams en `execute_command`. | **LOW** | ✅ Mitigado |
| **HARD-SSH-03** | `ssh` | **Higiene de Secretos en Memoria** (CWE-316): Retención indefinida de passphrases en atributos de workers y representación en `repr()`. | **LOW** | ✅ Mitigado |
| **HARD-CORE-02** | `core` | **Saneamiento de Rutas XDG** (CWE-20): Descarte de rutas relativas en variables XDG para evitar dependencia del CWD. | **LOW** | ✅ Mitigado |
| **HARD-CORE-03** | `core` | **Scrubbing de Secretos en Persistencia a Disco** (CWE-312): Depuración recursiva de claves sensibles antes de escribir JSON. | **LOW** | ✅ Mitigado |
| **HARD-SFTP-01** | `sftp` | **Permisos Restringidos en Descargas Locales** (CWE-732): Creación de archivos y carpetas con permisos seguros `0o600` y `0o700` en sistemas multi-usuario. | **LOW** | ✅ Mitigado |
| **HARD-UI-01** | `ui/docks` | **Validación de Rutas en Drag & Drop Dual** (CWE-22): Normalización y verificación de confinamiento canónico en transferencias soltadas. | **LOW** | ✅ Mitigado |
| **HARD-UI-02** | `ui/widgets` | **Prevención de Congelamiento por Flood de Datos en Terminal** (CWE-400): Inserción atómica en bloques de edición (`beginEditBlock`/`endEditBlock`). | **LOW** | ✅ Mitigado |

---

## 🔍 3. Detalle Técnico de las Mitigaciones Clave

### 3.1. Mitigación de Path Traversal y Jaula Canónica en SFTP
* **Problema:** En descargas recursivas, un atacante controlando el servidor SFTP podía inyectar nombres como `../../../../home/user/.bashrc`.
* **Solución Implementada:**
  1. Extracción forzada del nombre base con `posixpath.basename()` en `RemoteFileInfo.from_sftp_attr()` y `client.listdir_attr()`.
  2. Jaula canónica en `transfer_queue.py`: `target_local.resolve().relative_to(canonical_base)`. Cualquier intento de escape genera inmediatamente una excepción `SFTPError` y aborta la transferencia.
  3. Comprobación de `is_symlink()` para impedir la sobreescritura de enlaces simbólicos locales.

### 3.2. Aislamiento de Secretos y Cumplimiento RNF-03
* **Problema:** Riesgo de retención de passphrases y tokens en memoria no volátil, serializaciones accidentales en logs o archivos de configuración.
* **Solución Implementada:**
  1. `VolatileCredentialStore` retiene secretos bajo cerrojos `RLock` y expone un `__repr__` ofuscado (`<VolatileCredentialStore: N keys>`).
  2. Limpieza inmediata a `None` de referencias en memoria a contraseñas en el bloque `finally` de `SSHConnectionWorker`.
  3. `_scrub_secrets()` filtra recursivamente cualquier clave que contenga palabras como `password`, `token`, `secret`, `private_key` antes de guardar en `config.json` o `layout.json`.

### 3.3. Blindaje de Emulación de Terminal y PTY
* **Problema:** Un clúster remoto comprometido emitiendo secuencias de escape podía desbordar el búfer de la GUI, alterar títulos o inyectar comandos si el usuario pegaba texto malicioso.
* **Solución Implementada:**
  1. `ANSIParser`: Límites estrictos `MAX_BUFFER_LENGTH = 4096`, `MAX_CSI_LENGTH = 256`, `MAX_OSC_LENGTH = 1024`, `MAX_TITLE_LENGTH = 128`. Bloqueo explícito de OSC 52 (manipulación de portapapeles).
  2. `TerminalWidget.paste_to_terminal`: Saneamiento de texto pegado, eliminación de bytes de escape `\x1b`, bytes nulos `\x00` y límite máximo de 64 KB (`MAX_PASTE_BYTES`).
  3. `LocalPTYBackend`: Establecimiento explícito de `fcntl.FD_CLOEXEC` en el descriptor maestro PTY y cierre de rangos de descriptores (`os.closerange(3, 1024)`) en el hijo. Eliminación limpia de todo el grupo de procesos con `os.killpg(pid, signal.SIGHUP)` y recolección `waitpid` para evitar procesos zombies.

---

## 🧪 4. Resultados de la Suite de Pruebas de Seguridad

Se ejecutó la batería completa del proyecto en modo headless:
```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen pytest tests/ -v
```

### Métricas de Cobertura de Pruebas
| Suite de Pruebas | Tests | Estado | Foco Principal |
| :--- | :---: | :---: | :--- |
| `tests/test_config.py` | 9 | PASSED | Configuración XDG atómica y fallback ante corrupción. |
| `tests/test_signals.py` | 5 | PASSED | Event Hub desacoplado y ciclo de vida. |
| `tests/test_state.py` | 7 | PASSED | Serialización Base64 segura de layouts y docks. |
| `tests/test_ui_theme.py` | 8 | PASSED | Detección de tema oscuro/claro y QSS científico. |
| `tests/test_ssh_config.py` | 14 | PASSED | Parser OpenSSH, reglas first-match, alias y comodines. |
| `tests/test_ssh_client.py` | 19 | PASSED | Autenticación con llaves volátiles y workers asíncronos. |
| `tests/test_ssh_ui.py` | 16 | PASSED | Diálogos modales y visualización en árbol de clusters. |
| `tests/test_sftp_engine.py` | 13 | PASSED | Operaciones SFTP seguras, inodos y lazy loading. |
| `tests/test_sftp_transfer.py` | 10 | PASSED | Cola multihilo, SpeedTracker y cancelación. |
| `tests/test_sftp_ui.py` | 15 | PASSED | Árbol dual y drag & drop bidireccional. |
| `tests/test_terminal_ansi.py` | 24 | PASSED | Parser ANSI/VT100 TrueColor, 256 colores y control. |
| `tests/test_terminal_backend.py` | 15 | PASSED | Ciclo de vida LocalPTY y SSHPty interactivo. |
| `tests/test_terminal_ui.py` | 13 | PASSED | TerminalWidget, dock dinámico y atajos. |
| **`tests/test_security_core_ssh.py`** | **20** | **PASSED** | **Path traversal SFTP, inyección ProxyCommand, symlinks, scrubbing de secretos.** |
| **`tests/test_security_terminal_ui.py`** | **19** | **PASSED** | **ANSI buffer bloat, FD_CLOEXEC, procesos zombies, saneamiento de portapapeles y drag & drop.** |
| **TOTAL** | **207** | **100% PASSED** | **Zero fallos, zero vulnerabilidades residuales conocidas.** |

---

## 🏁 5. Conclusión y Dictamen de Auditoría
El código base de la **Fase 1 de HPC Studio Linux** cumple con los estándares más rigurosos de **seguridad por diseño (*security by design*)**, garantizando que el entorno sea robusto, confiable y seguro frente a servidores comprometidos, datos hostiles y accesos no autorizados en infraestructuras de supercómputo.

El sistema queda certificado como **seguro y listo para el inicio de la Fase 2**.
