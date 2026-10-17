# Portal de Documentación y Guía Maestra de Navegación — HPC Studio

Bienvenido al centro oficial de documentación de ingeniería, arquitectura, operación y recursos para agentes de **HPC Studio**. Este portal organiza los artefactos técnicos generados bajo rigurosos estándares de calidad (ISO/IEC/IEEE 29148, Modelo 4+1 de Kruchten, arc42/C4, Framework Diátaxis, normas ICONTEC y la especificación `llms.txt`).

---

## 🗺️ Mapa de Navegación del Repositorio de Documentación

```
docs/
├── README.md                                   # (Este archivo) Guía maestra de navegación
├── llms.txt                                    # Índice conciso estandarizado para agentes IA
├── llms-full.txt                               # Referencia técnica exhaustiva sin alucinaciones
│
├── informe/                                    # Informes Formales de Proyecto / Grado
│   └── informe_final_proyecto_icontec.md       # Informe final formal bajo normas ICONTEC / UdeC
│
├── requisitos/                                 # Ingeniería de Requisitos
│   └── especificacion_requisitos_iso29148.md   # Especificación de Requisitos ERS (ISO/IEC/IEEE 29148)
│
├── casos_de_uso/                               # Modelado de Comportamiento del Sistema
│   └── casos_de_uso_sistema.md                 # Catálogo tabular de casos de uso estructurados
│
├── arquitectura/                               # Arquitectura de Software y Modelos de Diseño
│   ├── manual_del_sistema_4mas1.md             # Manual del Sistema (Vistas 4+1 de Kruchten)
│   └── arquitectura_arc42_c4.md                # Descomposición del sistema bajo arc42 y modelos C4
│
├── adr/                                        # Architecture Decision Records
│   └── ADR_INDEX.md                            # Registro cronológico de decisiones arquitectónicas
│
├── usuario/                                    # Manual de Usuario y Guías Operativas
│   └── manual_de_usuario_diataxis.md           # Documentación de usuario bajo framework Diátaxis
│
└── api/                                        # Contratos e Interfaces de Software
    ├── openapi.json                            # Contrato de interfaz REST OpenAPI 3.1
    └── mcp_tools_reference.md                  # Especificación de herramientas Model Context Protocol (MCP)
```

---

## 📚 Categorías de Documentación

### 1. 🎓 Informe Final Institucional (ICONTEC / UdeC)
* [**Informe Final de Proyecto (Normas ICONTEC)**](informe/informe_final_proyecto_icontec.md): Documento formal de grado y memoria técnica del proyecto desarrollado para la Facultad de Ingeniería de la Universidad de Cartagena (Asesor: Ing. Martín Monroy Ríos, MSc, PhD). Incluye introducción, justificación, formulación de objetivos con taxonomía de Bloom, marco teórico (Slurm, Quantum ESPRESSO, Sidecar Supervisor, MCP), metodología de investigación DSRM, métricas de 421 pruebas unitarias y conclusiones orientadas al aprendizaje de ingeniería.

### 2. 📋 Ingeniería de Requisitos (ISO/IEC/IEEE 29148)
* [**Especificación de Requisitos de Software (ERS)**](requisitos/especificacion_requisitos_iso29148.md): Levantamiento formal de requisitos funcionales y no funcionales del sistema (seguridad en memoria volátil RNF-03, rendimiento de renderizado WebGL RNF-07, resiliencia ante cortes de red en canales SSH).
* [**Catálogo Tabular de Casos de Uso**](casos_de_uso/casos_de_uso_sistema.md): Descripción detallada de actores, precondiciones, flujo principal, flujos alternativos y postcondiciones para 32 casos de uso centrales.

### 3. 🏛️ Arquitectura y Diseño (Vistas 4+1, arc42 y C4)
* [**Manual del Sistema (Modelo de Vistas 4+1)**](arquitectura/manual_del_sistema_4mas1.md): Vistas Lógica, de Procesos, de Desarrollo, Física y de Escenarios según la taxonomía de Philippe Kruchten.
* [**Arquitectura de Sistema bajo arc42 y Diagramas C4**](arquitectura/arquitectura_arc42_c4.md): Descomposición en niveles Contexto (L1), Contenedores (L2), Componentes (L3) y Código (L4).
* [**Registro de Decisiones Arquitectónicas (ADRs)**](adr/ADR_INDEX.md): Decisiones clave registradas y justificadas (ADR-001: Desacoplamiento Sidecar en Python; ADR-002: Autenticación Efímera en Loopback; ADR-003: Renderizado 3D en WebGL).

### 4. 📖 Manual de Usuario (Framework Diátaxis)
* [**Manual de Usuario de HPC Studio**](usuario/manual_de_usuario_diataxis.md): Diseñado bajo los cuatro pilares de Diátaxis:
  - **Tutoriales (Aprendizaje guiado):** Primer cálculo SCF con Quantum ESPRESSO de punta a punta.
  - **Guías Paso a Paso (Orientadas a tareas):** Configuración de perfiles SSH con bastión `ProxyJump` y monitoreo de colas Slurm.
  - **Referencia Técnica (Orientada a la información):** Atajos de teclado, paleta de comandos y variables de configuración.
  - **Explicaciones Conceptuales (Orientadas al entendimiento):** Arquitectura del supervisor de procesos y ciclo de vida de los kernels ZeroMQ.

### 5. 🔌 Interfaces, Contratos y Especificación API
* [**Especificación OpenAPI 3.1**](api/openapi.json): Contrato JSON de endpoints REST del demonio FastAPI.
* [**Referencia de Herramientas MCP para Agentes IA**](api/mcp_tools_reference.md): Catálogo completo de las 18 herramientas expuestas por el servidor Model Context Protocol.

### 6. 🤖 Optimización para Agentes Autónomos de IA (`llms.txt`)
* [**Índice `llms.txt`**](llms.txt): Índice conciso y semántico optimizado para agentes de lenguaje (Google Antigravity, Claude, Copilot Workspace).
* [**Especificación Exhaustiva `llms-full.txt`**](llms-full.txt): Guía técnica profunda libre de ambigüedad con mapas de código fuente, flujos de handshake de tokens y rutinas de depuración.

---

## 🛠️ Comandos de Validación Rápida

Para verificar la integridad del proyecto y sus componentes:

```bash
# 1. Ejecutar las 421 pruebas unitarias e integrales del backend Python
.venv/bin/pytest -v

# 2. Compilar y verificar el tipado estricto de la extensión de VS Code
cd ../vscode/extensions/hpc-studio && npm run compile

# 3. Iniciar el demonio Sidecar en modo desarrollo
uv run python -m hpc_studio.server --port 8000 --debug
```
