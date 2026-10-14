# **HPC Studio Linux — Documentación de Avance**
## **Fase 2: Motor 3D, Form Builder y Analítica de Quantum ESPRESSO**

---

## 📌 1. Visión General de la Fase 2
La **Fase 2** expande la estación de trabajo hacia la física de la materia condensada, química cuántica y ciencia de materiales computacional. Proporciona herramientas nativas para la visualización cristalográfica 3D acelerada por hardware, la preparación y validación de simulaciones DFT (`pw.x`), la gestión de pseudopotenciales SSSP y el análisis de resultados de convergencia electrónica y fonónica.

### Estado de los Sprints de la Fase 2
| Sprint | Módulo / Alcance | Estado | Cobertura de Pruebas |
| :--- | :--- | :--- | :--- |
| **Sprint 2.1** | **Motor de Visualización 3D Cristalográfico y Parsers** | ✅ **Completado (100%)** | 23 / 23 pruebas superadas |
| **Sprint 2.2** | **Form Builder Quantum ESPRESSO (`pw.x`) & Sincronización** | ✅ **Completado (100%)** | 30 / 30 pruebas superadas |
| **Sprint 2.3** | **Gestor de Pseudopotenciales SSSP & SeeK-path** | ✅ **Completado (100%)** | 25 / 25 pruebas superadas |
| **Sprint 2.4** | **Parser de Salidas (`pw.out`) & Dashboard de Convergencia** | ✅ **Completado (100%)** | 18 / 18 pruebas superadas |

---

## 🚀 2. Avances Implementados en el Sprint 2.1

### 2.1. Núcleo Cristalográfico y Matemáticas de Estado Sólido (`src/hpc_studio/crystallography/`)

* **Datos Atómicos y Tabla Periódica ([`models.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/src/hpc_studio/crystallography/models.py)):**
  * `ElementData`: Datos exhaustivos para los 118 elementos de la tabla periódica, incluyendo número atómico $Z$, masa atómica estándar ($\text{u}$), radio covalente ($\text{Å}$), radio de van der Waals ($\text{Å}$) y paleta de colores CPK (Corey-Pauling-Koltun) en hexadecimal y RGB normalizado.
  * `Atom`: Representación de átomos con coordenadas Cartesianas ($x, y, z$), fraccionarias opcionales $(u, v, w)$, índice, símbolo químico y etiquetas de relajación.

* **Red Cristalina y Transformaciones de Celda:**
  * `Lattice`: Matriz de red $3\times3$ constituida por los vectores directos $\vec{a}, \vec{b}, \vec{c}$.
  * Cálculo exacto de longitudes de celda $a, b, c$, ángulos interaxiales $\alpha, \beta, \gamma$, volumen de la celda unitaria ($\text{Å}^3$) y matriz de la red recíproca $\vec{a}^*, \vec{b}^*, \vec{c}^*$.
  * Transformación bidireccional continua: `cartesian_to_fractional` y `fractional_to_cartesian`.

* **Estructura Cristalina y Operaciones Periódicas (`CrystalStructure`):**
  * `calculate_bonds(tolerance=0.45)`: Algoritmo de detección de enlaces químicos respetando radios covalentes bajo condiciones periódicas de contorno (PBC).
  * `create_supercell(nx, ny, nz)`: Generador de superceldas periódicas en $N_x \times N_y \times N_z$ multiplicando la matriz de red y replicando los sitios atómicos.
  * `distance(i, j, mic=True)`: Medición de distancias interatómicas aplicando la convención de mínima imagen (*Minimum Image Convention*).
  * `angle(i, j, k)` y `dihedral(i, j, k, l)`: Medición de ángulos de enlace y ángulos de torsión diedros.
  * `formula()`: Reducción estequiométrica para obtener la fórmula química empírica (ej. `Si`, `C`, `NaCl`, `TiO2`).

---

### 2.2. Parsers de Formatos Estructurales (`src/hpc_studio/crystallography/parsers/`)

* **Parser de CIF ([`cif.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/src/hpc_studio/crystallography/parsers/cif.py)):**
  * Soporte para el estándar *Crystallographic Information File* (`.cif`).
  * Lectura de loops de átomos `_atom_site_*`, constantes de red `_cell_length_*` y ángulos `_cell_angle_*`, generando una `CrystalStructure` normalizada.

* **Parser y Escritor de XYZ ([`xyz.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/src/hpc_studio/crystallography/parsers/xyz.py)):**
  * Lector y escritor compatible con archivos `.xyz` estándar y extendidos (propiedad `Lattice="a1 a2 a3 b1 b2 b3 c1 c2 c3"` en la línea de comentario).

* **Parser de Quantum ESPRESSO ([`qe.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/src/hpc_studio/crystallography/parsers/qe.py)):**
  * Extracción de estructuras directamente desde archivos de entrada `.in` de `pw.x`.
  * Soporte de redes de Bravais con `ibrav` (cúbica simple, FCC, BCC, hexagonal, tetragonal, etc.) y `celldm(1..6)` o bloque explícito `CELL_PARAMETERS` (en unidades alat, bohr o angstrom).
  * Soporte de `ATOMIC_POSITIONS` en modos `alat`, `bohr`, `angstrom` y `crystal`.

* **Escritores y Exportadores ([`writer.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/src/hpc_studio/crystallography/parsers/writer.py)):**
  * Exportación de estructuras a archivos `.cif` (`write_cif`), archivos `.xyz` (`write_xyz`) y generación de bloques formateados de `CELL_PARAMETERS` y `ATOMIC_POSITIONS` para Quantum ESPRESSO (`write_qe_blocks`).

---

### 2.3. Motor de Visualización 3D Interactivo (`src/hpc_studio/ui/viewers/crystal_3d/`)

* **Canvas 3D Acelerado por Hardware ([`crystal_viewer_widget.py`](file:///home/nosedimetuxd/GoogleDrive/dfrancob55/Entorno%20HPC/HPC%20Studio/src/hpc_studio/ui/viewers/crystal_3d/crystal_viewer_widget.py)):**
  * Embebe `pyvista` y `pyvistaqt.QtInteractor` dentro de un widget PySide6 nativo con aceleración OpenGL.
  * Dispone de un mecanismo de fallback seguro (`HeadlessFallbackCanvas`) para entornos sin servidor gráfico, ejecución remota o tests automatizados sin GPU.
  * **Renderizado de Elementos:**
    * **Átomos:** Esferas 3D con radio atómico proporcional y colores CPK de alto contraste.
    * **Enlaces:** Cilindros tridimensionales conectando pares de átomos coordinados.
    * **Celda Unidad:** Caja paralelepípedo en alambre con ejes de red rotulados y coloreados ($\vec{a}$ rojo, $\vec{b}$ verde, $\vec{c}$ azul).
    * **Etiquetas:** Conmutables para mostrar símbolo químico e índice del átomo.

* **Barra de Herramientas del Visor:**
  * Selector de Estilo: *Bolas y Varillas* (*Ball & Stick*), *Espacio Lleno* (*Space-Filling / vdW*) y *Alambre* (*Wireframe*).
  * Vistas Ortogonales: Botones rápidos para alinear la cámara al *Eje a*, *Eje b*, *Eje c* o *Vista Isométrica*.
  * Toggles de visualización: Caja de Celda Unitaria y Etiquetas Atómicas.
  * Selector de Supercelda: Expansión instantánea a $1\times1\times1$, $2\times2\times2$ o $3\times3\times3$.
  * Botón *Centrar* (reset camera) y *Exportar Imagen* (captura de pantalla PNG de alta resolución).

* **Telemetría y Estado:**
  * Barra inferior que reporta en tiempo real la fórmula química, cantidad total de átomos, parámetros de red ($a, b, c, \alpha, \beta, \gamma$), volumen en $\text{Å}^3$ e información del átomo seleccionado.

---

### 2.4. Integración en el IDE y Flujo de Trabajo

* **Pestañas de Documentos (`EditorArea`):**
  * Soporte nativo para abrir archivos `.cif` y `.xyz` en una pestaña dedicada del visor 3D con icono de cubo (`cube`).
  * Apertura de estructuras generadas en memoria mediante `open_structure(structure, title)`.
* **Explorador de Archivos:**
  * Al hacer doble clic en cualquier archivo `.cif` o `.xyz` del explorador local o remoto (SFTP), HPC Studio detecta la extensión y abre automáticamente el visor 3D interactivo.
* **Barra de Menús:**
  * `Herramientas -> Visualizador 3D de Estructuras (VTK/OpenGL)` abre al instante una estructura de muestra (Silicio diamantino $Fd\bar{3}m$ o Grafeno 2D).
  * `Archivo -> Nuevo Cálculo Quantum ESPRESSO (pw.x)` inicializa el editor híbrido bidireccional interactivo.

---

## ⚡ 3. Sprint 2.2: Motor de Inputs `pw.x`, Form Builder y Editor Híbrido Bidireccional

Se completó con éxito el **Sprint 2.2**, integrando la suite completa de modelado, serialización, parseo tolerante a fallas, validación semántica en tiempo real y el editor híbrido bidireccional para Quantum ESPRESSO.

### Arquitectura de Componentes
1. **Motor de Inputs & AST (`src/hpc_studio/qe/models.py`, `src/hpc_studio/qe/parser.py`)**:
   - Dataclasses tipadas para namelists estándar: `&CONTROL`, `&SYSTEM`, `&ELECTRONS`, `&IONS`, `&CELL`.
   - Cards estructuradas: `ATOMIC_SPECIES`, `ATOMIC_POSITIONS` (alat, bohr, angstrom, crystal con fijación `if_pos`), `K_POINTS` (automatic, gamma, crystal_b, tpiba_b) y `CELL_PARAMETERS`.
   - Conversión bidireccional completa hacia/desde `CrystalStructure` para renderizado tridimensional inmediato.
   - Parser AST tolerante con soporte de comentarios Fortran (`!`), mayúsculas/minúsculas indistintas, comas opcionales al final de línea y espacios flexibles.

2. **Validador Semántico (`src/hpc_studio/qe/validator.py`)**:
   - Detección de inconsistencias entre `nat` y la cantidad de posiciones atómicas declaradas.
   - Verificación de concordancia entre `ntyp` y las especies en `ATOMIC_SPECIES`.
   - Detección de especies no declaradas en las coordenadas.
   - Advertencia de cutoff para pseudopotenciales ultrasoft / PAW ($ecutrho < 4 \times ecutwfc$).
   - Advertencia de smearing sin ensanchamiento gaussiano ($degauss = 0$).
   - Requisito estricto de namelist `&IONS` en cálculos de relajación (`relax`, `vc-relax`).
   - Exigencia de `CELL_PARAMETERS` cuando `ibrav = 0`.

3. **Form Builder Científico (`src/hpc_studio/ui/qe/forms/`, `src/hpc_studio/ui/qe/qe_form_builder.py`)**:
   - Pestañas organizadas:
     * **&CONTROL**: Badges interactivos para cálculo (`scf`, `nscf`, `bands`, `relax`, `vc-relax`, `md`), prefijos, directorios de trabajo y modo de reinicio.
     * **&SYSTEM**: Catálogo de las 14 redes de Bravais (`ibrav`) con descripción geométrica, cutoffs de ondas planas y densidad de carga, smearing y magnetismo.
     * **&ELECTRONS**: Criterio de convergencia SCF (`conv_thr`), beta de mezclado y algoritmo de diagonalización (`david`, `cg`).
     * **Especies & Átomos**: Tablas interactivas con adición/eliminación de especies, asignación de masa y fichero UPF, y coordenadas atómicas con checkboxes para restricciones de relajación (`if_pos`).
     * **K-Points**: Selector de malla $k_x \times k_y \times k_z$ y shifts, con presets rápidos (*Gamma-only*, *Gruesa 2x2x2*, *Estándar 4x4x4*, *Fina 8x8x8*).
   - Badge dinámico de estado de validación con retroalimentación visual en tiempo real.

4. **Editor Híbrido Bidireccional (`src/hpc_studio/ui/qe/qe_hybrid_editor.py`)**:
   - `QSplitter` horizontal con vista ajustable:
     * **Panel Izquierdo:** `QEFormBuilder` interactivo.
     * **Panel Derecho:** Pestañas con `CodeEditor` (resaltado de sintaxis Fortran/QE con gutter de líneas) y `CrystalViewerWidget` (visor 3D acelerado por VTK/OpenGL).
   - **Sincronización en Tiempo Real:**
     * Cambio en el formulario $\rightarrow$ actualiza automáticamente el código y la celda 3D.
     * Edición en el código fuente $\rightarrow$ temporizador de *debounce* (350 ms) que re-parsea y actualiza los campos del formulario y el visor 3D sin desplazar el cursor.
   - Selector de disposición de pantalla: *Vista Dividida*, *Solo Formulario Gráfico*, o *Solo Código / Visor 3D*.

---

## 🔬 4. Sprint 2.3: Gestor de Pseudopotenciales SSSP & Generador SeeK-path

Se completó con éxito el **Sprint 2.3**, dotando a HPC Studio de una biblioteca curada de pseudopotenciales con verificación criptográfica y un asistente visual para la generación de caminos de alta simetría para cálculo de bandas.

### Arquitectura de Componentes
1. **Motor de Pseudopotenciales y Modelos (`src/hpc_studio/qe/pseudos/`)**:
   - `SSSPFamily`: Familias oficiales estándar `SSSP Efficiency 1.3.0`, `SSSP Precision 1.3.0`, `Pslibrary PAW 1.0.0` y `Custom`.
   - `PseudoMetadata`: Contrato completo con elemento químico, nombre del fichero UPF, tipo (`PAW`, `USPP`, `NC`, `SL`), funcional (`PBE`, `PZ`), cortes de energía recomendados ($ecutwfc$, $ecutrho$ en Ry), hash SHA256 y ruta en disco.
   - `UPFParser`: Parser nativo tolerante para cabeceras UPF versión 1 y versión 2 (XML y etiquetas individuales), extrayendo automáticamente valencia, malla y cutoffs.
   - `PseudoManager`: Catálogo local indexado con más de 70 elementos químicos, almacenamiento en caché local (`~/.cache/hpc_studio/pseudos/`), verificación de integridad SHA256 y escaneo de directorios arbitrarios.

2. **Generador de Caminos SeeK-path / Hinuma (`src/hpc_studio/crystallography/kpath.py`)**:
   - Detección automática de la red de Bravais a partir de la celda unitaria (`Lattice`, `CrystalStructure` o `QEInput`).
   - Soporte nativo para los caminos de alta simetría canónicos de Hinuma et al. (Comp. Mat. Sci. 2017) e integración opcional con la librería `seekpath`:
     * FCC (ibrav=2): $\Gamma - X - U - K - \Gamma - L - W - X$
     * BCC (ibrav=3): $\Gamma - H - P - \Gamma - N$
     * Cúbica Simple (ibrav=1): $\Gamma - X - M - \Gamma - R - X$
     * Hexagonal (ibrav=4): $\Gamma - M - K - \Gamma - A - L - H - A$
     * Tetragonal Simple (ibrav=6): $\Gamma - X - M - \Gamma - Z - R - A - Z$
   - `apply_to_qe_input`: Inyección directa del bloque `K_POINTS (crystal_b)` conmutando automáticamente `calculation = 'bands'` en `&CONTROL`.

3. **Interfaz de Usuario y Asistentes Gráficos (`src/hpc_studio/ui/qe/pseudos/`, `src/hpc_studio/ui/qe/kpath/`)**:
   - `PseudoManagerDialog`:
     * Selector de familia SSSP con buscador instantáneo y filtro por familia periódica.
     * Tabla interactiva con badges de tipo de pseudopotencial y estado local.
     * Descarga con barra de progreso y botón "Aplicar a la Simulación Actual" (asigna pseudopotenciales a las especies atómicas y ajusta $ecutwfc$/$ecutrho$ al valor máximo necesario).
     * Importación de archivos `.UPF` locales con cálculo de hash SHA256.
   - `KPathDialog`:
     * Diagrama de camino de alta simetría interactivo con nodos coloreados.
     * Tabla de segmentos con checkboxes para activar/desactivar, densidad de puntos por segmento ($N$), botones para subir/bajar e invertir el camino.
     * Previsualización en vivo del bloque formateado `K_POINTS (crystal_b)` con contador total de puntos k.
     * Botón "Insertar en Cálculo de Bandas".
   - Integración completa con botones en `QEFormBuilder` (pestañas Especies y K-Points), `QEHybridEditor` y el menú `Herramientas` de `HPCMainWindow`.

---

## 📊 5. Sprint 2.4: Parser de Salidas (`pw.out`), Monitor de Convergencia & Dashboard de Bandas / DOS

Se completó con éxito el **Sprint 2.4**, culminando la Fase 2 con una suite de análisis visual y métrico de cálculos DFT.

### Arquitectura de Componentes
1. **Motor de Parseo de Salidas y Modelos DFT (`src/hpc_studio/qe/output/`)**:
   - `ConvergenceStatus`: Estados normalizados `CONVERGED`, `NOT_CONVERGED`, `RUNNING` y `FAILED`.
   - `SCFIteration`: Historial de iteración ($E$, $\Delta E$, precisión estimada en Ry y tiempo CPU).
   - `IonicStep`: Registro de pasos de dinámica/relajación BFGS con fuerzas residuales, energía total, coordenadas atómicas y parámetros de celda.
   - `BandStructureData`: Autovalores de bandas en eV, energía de Fermi ($E_F$), Band Gap ($E_g$) y clasificación automática (Directo, Indirecto o Metálico).
   - `QEOutputParser`: Parser tolerante en streaming o texto completo con soporte para versiones modernas de Quantum ESPRESSO (v6.x - v7.x), capturando warnings, rutinas de error y reconstruyendo la `CrystalStructure` final para visualización 3D.

2. **Dashboard de Resultados y Visualizadores Gráficos (`src/hpc_studio/ui/qe/analytics/`)**:
   - `SCFConvergencePlotWidget`:
     * Renderizado científico oscuro (tema Matplotlib Dark).
     * Curvas de evolución de energía total y precisión estimada ($\log_{10}\text{Accuracy}$) con línea horizontal del umbral `conv_thr`.
     * Subplots automáticos para relajación iónica con evolución de energía por paso y fuerza residual máxima ($\text{Ry}/\text{Bohr}$).
   - `BandStructurePlotWidget`:
     * Gráfico de estructura de bandas electrónicas ($E - E_F$ en eV vs k-path).
     * Eje Y centrado en el nivel de Fermi ($E_F = 0\text{ eV}$) con línea punteada horizontal.
     * Detección y etiquetado de puntos de alta simetría ($\Gamma, X, W, K, L$) con líneas divisorias.
     * Anotación visual con badge del valor numérico del Band Gap y su carácter.
   - `QEResultsDashboard`:
     * Tarjetas métricas ejecutivas superiores (`MetricCard`): Estado DFT, Energía Total (Ry / eV), Pasos SCF e Iónicos, Band Gap y Tiempo Wall/CPU.
     * Pestañas integradas: *Convergencia SCF / Relajación*, *Estructura de Bandas*, *Geometría Final Relajada* (renderizado 3D interactivo con `CrystalViewerWidget`), y *Log de Salida Crudo* (con buscador incremental y resaltado de sintaxis).

3. **Integración en el Entorno de Trabajo**:
   - `EditorArea`: Abre automáticamente archivos `.out`, `.pwo` o logs con firma de Quantum ESPRESSO en una pestaña de `QEResultsDashboard`.
   - `HPCMainWindow`: Acción en menú `Herramientas -> Dashboard de Resultados DFT (pw.out)...`.
   - Explorador de archivos (local y remoto SFTP): Doble clic en salidas DFT carga el dashboard de resultados.

---

## 🧪 6. Verificación y Cobertura de Pruebas

El proyecto cuenta con **322 pruebas unitarias e integrales superadas con 100% de éxito**:
* `tests/test_crystallography_models.py`: 7 pruebas (propiedades de red, distancias MIC, ángulos, diedros, enlaces, superceldas).
* `tests/test_crystallography_parsers.py`: 6 pruebas (lectura/escritura CIF, XYZ y QE input con `ibrav` o `CELL_PARAMETERS`).
* `tests/test_crystal_viewer_ui.py`: 10 pruebas (renderizado 3D, estilos, superceldas, cámaras, exportación PNG, fallback headless e integración con `EditorArea`).
* `tests/test_qe_input_engine.py`: 18 pruebas (serialización y parseo de cálculos SCF/relax/vc-relax/bands, conversión bidireccional a estructuras cristalográficas y validaciones semánticas).
* `tests/test_qe_form_builder_ui.py`: 12 pruebas (ciclo de vida del Form Builder, sincronización bidireccional, presets de K-points, tablas de especies/posiciones y debounce del editor híbrido).
* `tests/test_qe_pseudos_and_kpath.py`: 16 pruebas (parseo UPF v1/v2, catálogo SSSP, cálculo y verificación SHA256, caminos canónicos SeeK-path FCC/BCC/SC/HEX e inyección en `QEInput`).
* `tests/test_qe_pseudos_ui.py`: 9 pruebas (diálogos `PseudoManagerDialog` y `KPathDialog`, filtrado, asignación automática de cutoffs a la simulación, manipulación de segmentos e integración de menú y barras de herramientas).
* `tests/test_qe_output_parser.py`: 6 pruebas (parseo de salidas SCF, relajación iónica con fuerzas, bandas con Fermi energy y gap, detección de no-convergencia y errores, y carga desde disco).
* `tests/test_qe_analytics_ui.py`: 12 pruebas (widgets `SCFConvergencePlotWidget`, `BandStructurePlotWidget`, `QEResultsDashboard`, búsqueda de logs e integración con `EditorArea`).
* Pruebas de regresión completas (terminal PTY, SFTP, SSH, gestor de temas y layout IDE): 226 pruebas.
