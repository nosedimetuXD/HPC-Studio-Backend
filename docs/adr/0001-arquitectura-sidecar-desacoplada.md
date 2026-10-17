# ADR-0001: Arquitectura Sidecar Desacoplada entre VS Code (TypeScript) y Demonio Local (Python)

* **Estado:** Aceptado
* **Decisores:** Equipo de Arquitectura de HPC Studio, Universidad de Cartagena
* **Fecha:** 2026-10-15
* **Estándar:** MADR 3.0.0

## Contexto y Definición del Problema

Visual Studio Code es el entorno de desarrollo líder para ingeniería y ciencia; sin embargo, su modelo de extensiones se basa en Node.js monohilo. Por otro lado, el ecosistema de computación científica, cristalografía (Ase, Pymatgen) y orquestación HPC (Paramiko, AsyncSSH, Slurm) está fundamentado de manera abrumadora en Python.

Intentar ejecutar cálculos cristalográficos masivos, análisis de salidas cuánticas voluminosas y múltiples hilos de red en el proceso de la extensión provocaría el bloqueo constante del hilo principal de UI (*Event Loop lag*), deteriorando la experiencia del usuario. Se requiere una solución que una la riqueza de interfaz de VS Code con la potencia científica de Python sin degradar el rendimiento.

## Factores de Decisión

* Rendimiento e interactividad: La interfaz de usuario debe mantenerse receptiva a 60 FPS sin importar el volumen de datos computados.
* Reutilización de librerías científicas maduras en Python (`ase`, `pymatgen`, `pydantic`, `fastapi`).
* Aislamiento de fallos: Un error o excepción en el motor cristalográfico o en la conexión SSH no debe tumbar el proceso de VS Code.
* Seguridad en la comunicación interproceso local.

## Opciones Consideradas

1. **Monolito en TypeScript:** Reescribir los motores cristalográficos, parsers de Quantum ESPRESSO y clientes SSH completamente en TypeScript/Node.js.
2. **Llamadas CLI Ad-hoc vía subprocesos (`child_process.exec`):** Invocar scripts individuales de Python mediante comandos CLI para cada acción del usuario.
3. **Arquitectura Sidecar Desacoplada:** Desplegar un demonio en segundo plano (*daemon*) con FastAPI en Python, gestionado por la extensión y comunicado vía HTTP/REST y Server-Sent Events (SSE) protegidos por token Bearer en loopback.

## Decisión Adoptada

Opción elegida: **Arquitectura Sidecar Desacoplada (Opción 3)**, debido a que ofrece el mejor equilibrio entre rendimiento en tiempo real, aislamiento de procesos y reutilización del ecosistema científico de Python.

### Consecuencias Positivas

* **Desempeño Óptimo:** Las operaciones intensivas (inversión de matrices de red, cálculo de caminos de Brillouin, streaming de logs) se ejecutan fuera del proceso de VS Code.
* **Persistencia de Estado y Pooling:** El demonio en Python mantiene en memoria pools de conexiones SSH abiertas, caché de estructuras cristalográficas y estados de trabajos Slurm, evitando el coste de inicialización continua.
* **Mantenibilidad:** El backend científico puede probarse de forma independiente mediante suites estándar de `pytest` sin requerir mocks del host de VS Code.

### Consecuencias Negativas

* **Consumo de Memoria:** Requiere un proceso de runtime Python co-localizado adicional en la máquina del usuario.
* **Complejidad de Orquestación:** La extensión debe gestionar el ciclo de vida del proceso hijo (arranque, verificación de salud, parada limpia ante cierre del IDE).

## Pros y Contras de las Opciones

### Monolito en TypeScript
* Bueno: No requiere dependencias de Python instaladas localmente.
* Malo: Ecosistema cristalográfico casi inexistente en Node.js; costo de reimplementación prohibitivo; riesgo severo de bloqueos del Event Loop.

### Llamadas CLI Ad-hoc
* Bueno: Fácil de invocar desde Node.js.
* Malo: Sobrecarga extrema al arrancar el intérprete de Python en cada interacción; imposible mantener conexiones SSH persistentes en memoria ni streaming reactivo eficiente.

### Arquitectura Sidecar Desacoplada
* Bueno: Máximo rendimiento, streaming en vivo con SSE, APIs fuertemente tipadas mediante OpenAPI/Pydantic y aislamiento total de fallos.
* Malo: Requiere implementar un handshake seguro para evitar que otros procesos en el sistema operativo ataquen el puerto local.
