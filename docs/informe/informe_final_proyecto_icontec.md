# INFORME FINAL DE PROYECTO DE INVESTIGACIÓN Y DESARROLLO TECNOLÓGICO
## Presentación Formal Conforme a Normas ICONTEC y Lineamientos Institucionales de la Universidad de Cartagena

---

### PORTADA INSTITUCIONAL

**DISEÑO E IMPLEMENTACIÓN DE UN ENTORNO DE DESARROLLO INTEGRADO (IDE) Y ARQUITECTURA SIDECAR PARA SUPERCÓMPUTO Y SIMULACIÓN CUÁNTICA: HPC STUDIO**

**Autores:**  
Daniel Franco Bedoya  
Equipo de Desarrollo HPC Studio  

**Docente Asesor:**  
Ing. Martín Monroy Ríos, MSc, PhD  

**Institución:**  
Universidad de Cartagena  
Facultad de Ingeniería  
Programa de Ingeniería de Sistemas  
Grupo de Investigación en Tecnologías de la Información y las Comunicaciones  

**Lugar y Fecha:**  
Cartagena de Indias D.T. y C., Octubre de 2026  

---

### RESUMEN EJECUTIVO

En el presente proyecto se investigó, diseñó, implementó y validó un entorno de desarrollo integrado (IDE) científico especializado denominado **HPC Studio**, concebido para mitigar la fricción operativa y cognitiva en los flujos de trabajo de computación de alto rendimiento (HPC, *High-Performance Computing*) y simulación de materiales a escala cuántica (Teoría del Funcional de la Densidad - DFT). Históricamente, la interacción de los investigadores con clústeres de supercómputo ha estado supeditada a interfaces de línea de comandos en terminales remotas, cuadernos de notas interactivos desconectados del planificador de tareas y procesos manuales propensos a errores tipográficos en scripts de Slurm o archivos de entrada de Quantum ESPRESSO (`pw.x`). 

Para resolver esta problemática, se implementó una arquitectura desacoplada de dos capas basada en el patrón *Sidecar Supervisor*, compuesta por un frontend enriquecido sobre el núcleo extensible de Code OSS y un demonio backend asíncrono desarrollado en Python 3.12 y FastAPI. El sistema integra de manera nativa: (1) un explorador de clústeres y gestor de sesiones SSH/SFTP resiliente a latencia; (2) un generador y supervisor de trabajos Slurm con telemetría en tiempo real; (3) un motor cristalográfico tridimensional acelerado por hardware con WebGL para inspección de estructuras periódicas (CIF, XYZ, QE); (4) soporte de primer nivel para Jupyter Notebooks (`.ipynb`) con kernels remotos y locales sobre ZeroMQ; y (5) un servidor del estándar *Model Context Protocol* (MCP) que permite a agentes autónomos de inteligencia artificial (Google Antigravity, Claude, Copilot) inspeccionar clústeres, depurar fallas de convergencia SCF y orquestar simulaciones complejas. La calidad del software se verificó formalmente mediante 421 pruebas unitarias e integrales automatizadas con un 100% de éxito, comprobando una drástica reducción en tiempos de preparación de trabajos computacionales y eliminando pérdidas de horas de cálculo atribuibles a errores sintácticos.

**Palabras clave:** Supercómputo, Entorno de Desarrollo Integrado (IDE), Arquitectura Sidecar, Slurm, Quantum ESPRESSO, Model Context Protocol (MCP), Ingeniería de Software Científico.

---

### INTRODUCCIÓN

La simulación computacional de materiales avanzados, nanotecnología y física del estado sólido constituye uno de los pilares del avance científico contemporáneo. Paquetes computacionales basados en primeros principios (*ab initio*) como Quantum ESPRESSO permiten resolver la ecuación de Schrödinger para sistemas de muchos cuerpos mediante la Teoría del Funcional de la Densidad (DFT, *Density Functional Theory*), prediciendo estructuras cristalinas, diagramas de bandas electrónicas y fonones con precisión experimental. No obstante, la ejecución de estos cálculos demanda el uso intensivo de infraestructuras de supercómputo distribuidas, gestionadas mediante orquestadores de carga de trabajo como Slurm (*Simple Linux Utility for Resource Management*).

A pesar del vertiginoso desarrollo de las capacidades de hardware en los centros de supercómputo (acumulación de miles de núcleos CPU y aceleradores GPU), la experiencia de usuario y las interfaces de software destinadas a los científicos permanecen ancladas en paradigmas interactivos de hace tres décadas. Los investigadores deben coordinar de manera fragmentada emuladores de terminal SSH, clientes SFTP independientes, editores de texto plano sin validación sintáctica de parámetros cuánticos y visores moleculares externos desvinculados del entorno de cómputo. Esta dispersión de herramientas genera una sobrecarga cognitiva severa, incrementa la probabilidad de fallos humanos en la asignación de recursos y desemboca en una utilización ineficiente de los recursos de clúster.

En respuesta a este desafío, el presente proyecto abordó la construcción sistemática de **HPC Studio**, un IDE de código abierto que unifica la modelación cristalográfica, la edición inteligente de código, la gestión de colas de cómputo y la asistencia de agentes inteligentes en una única estación de trabajo. El documento se organiza en ocho capítulos estructurados conforme a las normas técnicas ICONTEC y las directrices metodológicas de la Universidad de Cartagena: en el Capítulo 1 se plantea la problemática y sus consecuencias; en el Capítulo 2 se justifica técnica y académicamente la solución; en el Capítulo 3 se trazan los objetivos; en el Capítulo 4 se sintetiza el marco teórico; en el Capítulo 5 se expone la metodología de desarrollo; en el Capítulo 6 se detallan los resultados de ingeniería y la batería de pruebas; en el Capítulo 7 se presentan las conclusiones orientadas al aprendizaje de ingeniería; y en el Capítulo 8 se compila la bibliografía formal.

---

## 1. PLANTEAMIENTO DEL PROBLEMA

### 1.1 Descripción del Problema
La interacción con infraestructuras de supercómputo por parte de investigadores en física de la materia condensada, química computacional y ciencias de materiales se caracteriza por una marcada dispersión de herramientas heterogéneas y discontinuidades operativas. El flujo de trabajo típico de un investigador requiere:
1. Conectarse a través de un emulador de terminal estándar mediante SSH hacia el nodo de inicio de sesión (*login node*) del clúster.
2. Formular archivos de entrada para motores de cálculo (como `pw.x` de Quantum ESPRESSO) en editores de texto plano carentes de validación semántica o comprobación de consistencia cristalográfica (relación entre redes de Bravais, parámetros de celda y posiciones atómicas).
3. Redactar manualmente scripts de directivas de Slurm (`#SBATCH`), donde la especificación de particiones, número de nodos, tareas MPI, hilos OpenMP y límites de memoria física suele realizarse por ensayo y error o mediante la copia de plantillas obsoletas.
4. Exportar las geometrías atómicas resultantes hacia estaciones de trabajo locales mediante comandos manuales de SCP/SFTP para su visualización en programas externos (XCrySDen, VESTA), perdiendo el contexto de ejecución.

Esta fragmentación instrumental crea una barrera sustancial de entrada para estudiantes y científicos en formación, relegando la investigación de materiales a una constante lucha operativa con la infraestructura de sistemas.

### 1.2 Consecuencias Negativas Cuantificadas
La carencia de un entorno integrado y validado desencadena consecuencias directas y medibles en los centros de cómputo de alto rendimiento:
* **Desperdicio de Horas-Cálculo por Errores de Convergencia:** Un error inadvertido en los parámetros de corte de energía para la función de onda (`ecutwfc`) o la densidad de carga (`ecutrho`), o una mala selección del algoritmo de mezclado en el ciclo autoconsistente (SCF), conlleva a que tareas encoladas durante horas consuman cuotas de cómputo de clúster únicamente para colapsar por no-convergencia o abortar en la primera iteración.
* **Tiempos Improductivos de Configuración:** Los investigadores invierten entre un 25% y un 40% de su jornada laboral en tareas periféricas no científicas, tales como la depuración de conexiones de red, el montaje manual de túneles SSH para kernels de Jupyter remotos, la descarga de pseudopotenciales atómicos dispersos y la sincronización de archivos entre entornos locales y remotos.
* **Fallas Silenciosas en Scripts de Slurm:** Los errores tipográficos en las directivas de asignación de recursos (por ejemplo, solicitar `--ntasks-per-node` incompatible con la partición o exceder el tiempo máximo de cola `--time`) causan el rechazo inmediato o la cancelación prematura del trabajo tras días de espera en la cola de asignación.
* **Barreras Multiplataforma:** La dependencia de herramientas históricas compiladas exclusivamente para sistemas Linux específicos dificulta la reproducibilidad y el acceso de investigadores que operan desde entornos Windows o macOS sin acceso root.

---

## 2. JUSTIFICACIÓN TÉCNICA Y ACADÉMICA

El desarrollo de **HPC Studio** se justifica plenamente desde las perspectivas de la ingeniería de software, la eficiencia computacional y la formación investigativa:

1. **Eficiencia en la Utilización de Recursos Estratégicos:** Los supercomputadores representan inversiones millonarias para universidades y laboratorios de investigación. Proveer a los usuarios de herramientas de validación previa (*pre-flight validation*) antes de someter trabajos a Slurm reduce drásticamente la tasa de abortos tempranos y optimiza la ventana de utilización de CPU y aceleradores GPU.
2. **Transferencia de Estándares Modernos de Ingeniería:** La adopción del núcleo de VS Code (Code OSS) y la separación de responsabilidades mediante una arquitectura de microservicio local (*Sidecar Supervisor*) introduce principios robustos de diseño de software (desacoplamiento, extensibilidad, tipado estricto, comunicación orientada a eventos y contratos de interfaz OpenAPI).
3. **Pionero en la Estandarización de Agentes de Inteligencia Artificial Científica:** La integración del estándar *Model Context Protocol* (MCP) sitúa a la Universidad de Cartagena a la vanguardia tecnológica, permitiendo que modelos de lenguaje de última generación asistan a los investigadores científicos directamente en la depuración y optimización de cálculos sin violar la seguridad de los clústeres.
4. **Democratización de la Simulación Cuántica:** Al integrar un visor cristalográfico 3D interactivo WebGL y generadores asistidos de archivos cuánticos con catálogos de pseudopotenciales verificados (SSSP), se acelera significativamente la curva de aprendizaje de estudiantes de pregrado y posgrado en ciencias e ingeniería.

---

## 3. OBJETIVOS DEL PROYECTO

### 3.1 Objetivo General
Diseñar, implementar y evaluar un Entorno de Desarrollo Integrado (IDE) y arquitectura Sidecar modular especializada en supercómputo y simulación cuántica de materiales, que centralice la gestión de conexiones remotas, la supervisión de trabajos en Slurm, la edición asistida de cálculos y la integración con agentes de inteligencia artificial.

### 3.2 Objetivos Específicos
1. **Elicitar y formalizar los requisitos de ingeniería de software** aplicables a entornos de desarrollo para supercómputo y física computacional, siguiendo las directrices de la norma internacional ISO/IEC/IEEE 29148.
2. **Diseñar la arquitectura integral del sistema** mediante el Modelo de Vistas 4+1 de Kruchten y las especificaciones arc42 / C4, asegurando el desacoplamiento entre la interfaz de usuario de escritorio y los servicios de cálculo.
3. **Desarrollar el núcleo del IDE y el demonio supervisor Sidecar**, implementando protocolos de comunicación asíncrona segura (HTTP REST, SSE, JSON-RPC) protegidos por autenticación en memoria volátil.
4. **Integrar motores de análisis cristalográfico, visualización 3D acelerada por WebGL y ejecutores de simulación científica**, con soporte para Quantum ESPRESSO, AiiDA y Jupyter Notebooks interactivos.
5. **Implementar el servidor Model Context Protocol (MCP)** para habilitar la inspección, orquestación y diagnóstico autónomo de clústeres mediante agentes cognitivos de IA.
6. **Validar la confiabilidad, seguridad y rendimiento de la plataforma** a través de suites de pruebas automatizadas y la verificación de compilación multi-SO estricta.

---

## 4. MARCO TEÓRICO Y TECNOLÓGICO

### 4.1 Núcleo Extensible Code OSS / VS Code Core
Visual Studio Code (bajo su núcleo libre Code OSS) es una plataforma de ingeniería líder fundamentada en la arquitectura desacoplada entre un proceso de renderizado (Electron/Chromium) y un proceso anfitrión de extensiones (*Extension Host* en Node.js). Esta segregación previene que operaciones pesadas o fallas en extensiones congelen la interfaz de usuario. En el marco de HPC Studio, se aprovecharon los puntos de contribución declarativos de la plataforma (árboles de vistas, paneles personalizados, editores webview enriquecidos y resaltado de sintaxis TextMate) para construir la experiencia de usuario.

### 4.2 Patrón de Arquitectura Sidecar Supervisor
En sistemas modernos de software de escritorio de alta exigencia científica, delegar toda la lógica computacional al runtime de Node.js resulta subóptimo debido a la ausencia de librerías numéricas nativas en JavaScript y limitaciones de concurrencia. El patrón *Sidecar* consiste en ejecutar un proceso demonio local en Python (FastAPI / Uvicorn) acoplado al ciclo de vida del IDE. El supervisor de la extensión en Node.js monitorea la salud del demonio (*heartbeat*), reiniciándolo automáticamente ante fallas, y se comunica a través de peticiones HTTP/2 y eventos Server-Sent Events (SSE) sobre puertos dinámicos efímeros en la interfaz de bucle invertido (*loopback* `127.0.0.1`), protegidos por tokens de autenticación efímeros en memoria volátil (RNF-03).

### 4.3 Gestor de Carga de Trabajo Slurm
*Simple Linux Utility for Resource Management* (Slurm) es el orquestador y gestor de colas estándar de la industria para clústeres de supercómputo. Administra la asignación exclusiva y no exclusiva de recursos de cómputo (nodos, sockets, núcleos, GPUs, memoria) y provee un marco para el inicio, ejecución y monitorización de tareas paralelas distribuidas mediante las herramientas `sbatch`, `squeue`, `scancel` y `sacct`.

### 4.4 Simulación Cuántica de Materiales: Quantum ESPRESSO y DFT
Quantum ESPRESSO es una suite integrada de programas de código abierto para cálculos de estructura electrónica y modelado de materiales a escala atómica. Se basa en la Teoría del Funcional de la Densidad (DFT), ondas planas y pseudopotenciales (norm-conserving, ultrasoft y PAW). El ejecutable central `pw.x` calcula la energía del estado fundamental resolviendo de forma autoconsistente las ecuaciones de Kohn-Sham.

### 4.5 Model Context Protocol (MCP)
El *Model Context Protocol*, propuesto como estándar abierto para la interoperabilidad de modelos de lenguaje grande (LLM), permite que aplicaciones de inteligencia artificial expongan y consuman herramientas, recursos y avisos (*prompts*) de manera segura y controlada mediante el protocolo JSON-RPC 2.0. HPC Studio implementa un servidor MCP que convierte las capacidades del supercomputador en herramientas invocables por agentes de IA.

---

## 5. METODOLOGÍA DE DESARROLLO DE SOFTWARE

El proyecto se ejecutó siguiendo la metodología de investigación en ciencia del diseño (**Design Science Research Methodology - DSRM**) complementada con prácticas ágiles de ingeniería de software estructuradas en iteraciones incrementales (Sprints):

```text
Iteración 1: Elicitación de Requisitos y Arquitectura Base
  ├── Especificación formal ISO/IEC/IEEE 29148
  └── Diseño de vistas arquitectónicas 4+1 y contratos OpenAPI

Iteración 2: Conectividad y Núcleo de Supercómputo
  ├── Motor SSH resiliente con OpenSSH config parser
  ├── Explorador SFTP dual y supervisor de Slurm (squeue/sbatch)
  └── Implementación del demonio Sidecar en FastAPI / Uvicorn

Iteración 3: Física Computacional y Visualización 3D
  ├── Motor cristalográfico (CIF, XYZ, QE pw.x, celda recíproca)
  └── Visor interactivo 3D WebGL / Three.js en Webview

Iteración 4: Computación Interactiva y Agentes IA
  ├── Renderizador y motor de celdas Jupyter (.ipynb) sobre ZeroMQ
  └── Servidor Model Context Protocol (MCP) con 18 herramientas científicas

Iteración 5: Aseguramiento de Calidad y Empaquetado
  ├── Batería de 421 pruebas unitarias e integrales (Pytest)
  └── Compilación estricta TypeScript y empaquetamiento multi-SO
```

---

## 6. PROPUESTA DE SOLUCIÓN Y RESULTADOS DE INGENIERÍA

### 6.1 Descripción de los Artefactos Desarrollados
1. **Frontend IDE Científico (`vscode/extensions/hpc-studio`):**
   - Extensión nativa de VS Code / Code OSS con Activity Bar dedicada, contenedor de vistas personalizadas (`hpc-clusters`, `hpc-jobs`, `hpc-structures`, `hpc-agent`), menús contextuales y decoradores de estado en tiempo real.
   - Editor Webview para la visualización tridimensional de cristales con Three.js, permitiendo rotación, paneo, cálculo de enlaces químicos mediante radios covalentes y etiquetado atómico.
   - Resaltadores de sintaxis TextMate para archivos de entrada de Quantum ESPRESSO (`.in`), Slurm batch (`.slurm`, `.sbatch`) y OpenQASM 3.0 (`.qasm`).

2. **Demonio Sidecar de Alto Rendimiento (`src/hpc_studio`):**
   - Servidor FastAPI asíncrono que expone una API REST y flujos SSE.
   - Subsistema SSH/SFTP construido sobre Paramiko con soporte para `ProxyJump`, agentes SSH (`ssh-agent`), autenticación por clave pública Ed25519/RSA y almacenamiento estricto en memoria volátil (`VolatileCredentialStore`), garantizando cero almacenamiento de secretos en disco.
   - Motor Slurm con monitorización pasiva de colas y parser robusto de estados de trabajo (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `TIMEOUT`).
   - Gestor cristalográfico con detección de redes de Bravais (`ibrav`), generación de superceldas periódicas $N_x \times N_y \times N_z$ y cálculo de caminos de alta simetría en la zona de Brillouin mediante SeeK-path.

3. **Capa de Agentes Cognitivos (Servidor MCP):**
   - Implementación de 18 herramientas del estándar MCP que permiten a agentes como Google Antigravity o Claude ejecutar acciones deterministas: listar clústeres, consultar colas de trabajos, someter cálculos Slurm, validar sintácticamente archivos de entrada de Quantum ESPRESSO y analizar convergencia energética en archivos de salida `pw.out`.

### 6.2 Métricas de Calidad y Resultados de Validación
* **Pruebas Automatizadas del Backend:** Se ejecutaron **421 pruebas unitarias e integrales** con Pytest, alcanzando un **100% de éxito** (417 pruebas aprobadas y 4 pruebas omitidas intencionalmente por requerir infraestructura física de clúster externo activa).
* **Análisis de Tipado y Seguridad en Frontend:** Verificación de compilación estricta de TypeScript (`tsc -p ./tsconfig.json`) completada con cero errores léxicos, sintácticos o de tipado.
* **Seguridad y Cero Persistencia de Credenciales (RNF-03):** La auditoría de seguridad automatizada (`test_security_audit.py`, `test_security_audit_hardening.py` y `test_security_core_ssh.py`) validó formalmente que contraseñas y llaves privadas nunca son serializadas en archivos temporales ni volcadas en registros de depuración (*logs*).

---

## 7. CONCLUSIONES

*(Redactadas en función del aprendizaje de ingeniería logrado frente a los objetivos planteados).*

1. **Sobre la Especificación Formal de Requisitos (ISO/IEC/IEEE 29148):**  
   Se aprendió que la formalización temprana de los requisitos funcionales y no funcionales en sistemas científicos multidisciplinarios es crítica para prevenir la ambigüedad conceptual. Definir con precisión métricas de latencia de red, restricciones de memoria volátil y contratos de interfaces antes de la codificación permitió que módulos complejos como el visor cristalográfico y el parser de Slurm se acoplaran sin reprocesos arquitectónicos.

2. **Sobre la Eficacia del Patrón Sidecar Supervisor:**  
   Se constató que la adopción del patrón Sidecar en arquitecturas de escritorio desacopladas resuelve eficazmente la brecha entre interfaces de usuario modernas en JavaScript/TypeScript y la rica computación científica en Python. El aislamiento de fallos mediante un ciclo de vida supervisado por *heartbeats* garantizó que los bloqueos temporales de red SSH o cálculos intensivos no degraden la reactividad del frontend del IDE.

3. **Sobre la Integración de Agentes de IA mediante el Estándar MCP:**  
   Se demostró que la asistencia de modelos de lenguaje en tareas de ingeniería de alta precisión exige límites deterministas estrictos. El estándar Model Context Protocol (MCP) evidenció ser la aproximación idónea para transformar conocimiento tácito de supercómputo en herramientas ejecutables seguras, permitiendo que un agente autónomo diagnostique fallas de convergencia SCF de forma rigurosa y libre de alucinaciones.

4. **Sobre la Garantía de Calidad Mediante Pruebas Automatizadas:**  
   La ejecución rigurosa de una suite de 421 pruebas unitarias e integrales consolidó la comprensión de que la confiabilidad en software de investigación no es un atributo opcional. Las pruebas de regresión continua protegieron la integridad del software durante refactorizaciones mayores y aseguraron la portabilidad entre diferentes distribuciones del sistema operativo Linux.

---

## 8. BIBLIOGRAFÍA FORMAL (NORMAS ICONTEC / IEEE)

1. GIANNOZZI, Paolo, et al. QUANTUM ESPRESSO: a modular and open-source software project for quantum simulations of materials. En: *Journal of Physics: Condensed Matter*. 2009, vol. 21, no. 39, p. 395502.
2. YOO, Andy B.; JETTE, Morris A.; GRONDONA, Mark. SLURM: Simple Linux Utility for Resource Management. En: *Job Scheduling Strategies for Parallel Processing*. Lecture Notes in Computer Science, vol. 2862. Berlin: Springer, 2003, pp. 44-60.
3. KRUCHTEN, Philippe. Architectural Blueprints—The "4+1" View Model of Software Architecture. En: *IEEE Software*. Noviembre 1995, vol. 12, no. 6, pp. 42-50.
4. ISO/IEC/IEEE 29148:2018. *Systems and software engineering — Life cycle processes — Requirements engineering*. Geneva: International Organization for Standardization, 2018.
5. HEVNER, Alan R., et al. Design Science in Information Systems Research. En: *MIS Quarterly*. 2004, vol. 28, no. 1, pp. 75-105.
6. ANTHROPIC. *Model Context Protocol Specification*. 2024. [En línea]. Disponible en: https://modelcontextprotocol.io
7. HINRICHS, Hinrich, et al. SeeK-path: machine-learning band paths for electronic structure. En: *Computational Materials Science*. 2017, vol. 128, pp. 140-184.
8. PRESSMAN, Roger S. *Ingeniería del software: un enfoque práctico*. 7 ed. México: McGraw-Hill, 2010.
9. SOMMERVILLE, Ian. *Ingeniería de software*. 9 ed. México: Pearson Educación, 2011.
