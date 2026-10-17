# ADR-0002: Adopción del Servidor MCP Stdio para Exposición de Capacidades a Agentes de IA

* **Estado:** Aceptado
* **Decisores:** Equipo de Arquitectura de HPC Studio, Universidad de Cartagena
* **Fecha:** 2026-10-15
* **Estándar:** MADR 3.0.0

## Contexto y Definición del Problema

La integración de Modelos de Lenguaje Grande (LLMs) y agentes inteligentes autónomos en el flujo de trabajo científico requiere un mecanismo seguro, estandarizado y tipado para consultar clústeres Slurm, validar geometrías atómicas y leer archivos de simulación. Históricamente, cada asistente de código utiliza formatos propietarios de llamada a funciones (*Function Calling*), dificultando la portabilidad y creando acoplamientos rígidos con proveedores comerciales.

## Factores de Decisión

* Adhesión a estándares abiertos de la industria de Inteligencia Artificial.
* Soporte para transporte estándar sobre canales seguros de entrada/salida (`stdio` JSON-RPC).
* Tipado estricto mediante esquemas JSON Schema para validación de argumentos.
* Compatibilidad nativa con múltiples agentes (Antigravity, Claude Desktop, Cursor, Continue).

## Opciones Consideradas

1. **APIs Propietarias de Function Calling:** Integrar llamadas específicas en formato OpenAI Assistants API o Anthropic Tools directamente en el frontend.
2. **REST Endpoints Expuestos al Modelo:** Permitir al agente realizar peticiones HTTP arbitrarias contra el demonio FastAPI.
3. **Servidor MCP Stdio (Model Context Protocol v2024-11-05):** Implementar un servidor formal bajo el protocolo abierto MCP utilizando el transporte `stdio`.

## Decisión Adoptada

Opción elegida: **Servidor MCP Stdio (Opción 3)**, implementando `hpc_studio.mcp` conforme a la especificación oficial de Anthropic.

### Consecuencias Positivas

* **Estandarización Universal:** Las herramientas de HPC Studio (`validate_qe_input`, `inspect_slurm_queue`, `calculate_kpath`, `inspect_cluster`) se exponen como recursos y herramientas estándar del protocolo MCP.
* **Seguridad por Transporte Stdio:** Al comunicarse mediante flujos de entrada/salida estándar (`stdin`/`stdout`), no se abren puertos de red adicionales expuestos a la red local.
* **Interoperabilidad:** Cualquier cliente compatible con MCP puede utilizar las herramientas de HPC Studio de forma inmediata.

### Consecuencias Negativas

* **Dependencia de la especificación MCP:** Cambios mayores en la especificación del protocolo requerirán actualizar el servidor.
* **Serialización JSON-RPC:** Toda la comunicación debe serializarse en texto JSON-RPC, lo que requiere optimizar el tamaño de los payloads cristalográficos retornados.

## Pros y Contras de las Opciones

### APIs Propietarias
* Bueno: Fácil de cablear directamente con un solo proveedor.
* Malo: Cautiverio de proveedor (*vendor lock-in*); no es interoperable con agentes locales ni de código abierto.

### REST Endpoints Directos
* Bueno: Reutiliza los endpoints ya existentes en FastAPI.
* Malo: Requiere que el modelo gestione cabeceras de autorización Bearer y puertos TCP dinámicos; propenso a errores de conexión.

### Servidor MCP Stdio
* Bueno: Estándar moderno abierto, transporte seguro sin puertos expuestos, validación formal de esquemas con Pydantic y soporte multi-agente.
* Malo: Requiere empaquetar un punto de entrada ejecutable `hpc-studio-mcp`.
