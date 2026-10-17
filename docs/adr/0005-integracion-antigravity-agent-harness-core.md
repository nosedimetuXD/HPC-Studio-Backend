# ADR-0005: Integración del Antigravity Agent Harness como SessionType de Primer Nivel en VS Code

* **Estado:** Aceptado
* **Decisores:** Equipo de Arquitectura de HPC Studio, Universidad de Cartagena
* **Fecha:** 2026-10-15
* **Estándar:** MADR 3.0.0

## Contexto y Definición del Problema

La simulación de materiales y la computación de alto rendimiento enfrentan tasas altas de fallo debidas a divergencia de convergencia SCF, mala elección de parámetros cuánticos (como valores insuficientes de `ecutwfc` o mallas de k-points dispersas) y errores en directivas de colas Slurm. Los investigadores necesitan un asistente inteligente que no sea un simple chat genérico de texto, sino un **agente de software autónomo y proactivo** con conocimiento del contexto del espacio de trabajo, capaz de ejecutar diagnósticos guiados, invocar herramientas MCP y realizar streaming de respuestas en tiempo real.

En el núcleo de VS Code, la arquitectura de chat (`vscode.chat`) admite la definición de participantes y proveedores de sesión (`SessionType`). Es imperativo integrar el arnés de agentes **Antigravity** de forma nativa en el core para habilitar una experiencia conversacional y resolutiva profunda.

## Factores de Decisión

* Integración nativa con la interfaz de usuario de VS Code Workbench sin requerir plugins de terceros.
* Soporte para streaming de tokens reactivo (Server-Sent Events / Async Iterators).
* Capacidad de ejecutar herramientas (MCP Tools) con bucle de razonamiento de múltiples pasos (*Thought -> Action -> Observation -> Response*).
* Aislamiento de sesiones y persistencia de memoria conversacional en el backend.

## Opciones Consideradas

1. **Panel Webview Personalizado para Chat:** Construir una interfaz de chat web independiente dentro de un panel Webview aislado.
2. **Consola de Terminal Basada en Texto:** Ejecutar el agente exclusivamente como una herramienta CLI interactiva en la terminal integrada.
3. **Registro de Antigravity como SessionType y Chat Participant de Primer Nivel:** Extender la API nativa de VS Code registrando un participante formal (`@hpc` / `antigravity`) respaldado por el módulo `hpc_studio.agent.bridge`.

## Decisión Adoptada

Opción elegida: **Integración como SessionType y Chat Participant Nativo (Opción 3)**.

### Consecuencias Positivas

* **Experiencia de Usuario Fluida:** El usuario interactúa con el agente en la barra lateral oficial de chat de VS Code, disfrutando de atajos de teclado nativos, bloques de código interactivos, botones de inserción directa en el editor y comandos barra (`/slurm`, `/diagnose`, `/crystal`).
* **Streaming de Eventos Estructurados:** El puente del agente (`agent/bridge.py` y `agent/events.py`) transmite eventos granulares (`ThoughtEvent`, `ToolCallEvent`, `ToolResultEvent`, `TokenChunkEvent`), permitiendo a la UI mostrar visualmente el proceso de razonamiento del agente antes de la respuesta final.
* **Orquestación MCP Transparente:** El agente consume de forma nativa las herramientas registradas en `hpc_studio.mcp.tools` sin puentes intermedios frágiles.

### Consecuencias Negativas

* **Dependencia de la API de Chat de VS Code:** Requiere compatibilidad con las APIs de chat propuestas o estables de las versiones recientes de VS Code.
* **Gestión de Cancelación Asíncrona:** Cuando el usuario presiona el botón "Detener generación", se deben cancelar de forma segura los hilos de inferencia del LLM y las llamadas activas a herramientas en el demonio.

## Pros y Contras de las Opciones

### Webview Personalizado
* Bueno: Control estético total del HTML/CSS de la ventana de chat.
* Malo: No se integra con los atajos globales ni con los menús contextuales de código del editor; duplica esfuerzo de accesibilidad y temas visuales.

### Terminal CLI
* Bueno: Muy ligero de implementar.
* Malo: Cero interactividad gráfica; no permite renderizar tablas formateadas, diagramas ni botones de aplicación de parches en código.

### Chat Participant Nativo (Antigravity)
* Bueno: Máxima ergonomía en el IDE, soporte para comandos barra, visualización transparente de llamadas a herramientas MCP y streaming robusto de tokens.
* Malo: Requiere mantener sincronizados los modelos de eventos entre TypeScript y Python.
