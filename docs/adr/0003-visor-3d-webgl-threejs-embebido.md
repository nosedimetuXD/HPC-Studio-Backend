# ADR-0003: Visor 3D WebGL (Three.js) Embebido en Webview vs Herramientas Externas de Escritorio

* **Estado:** Aceptado
* **Decisores:** Equipo de Arquitectura de HPC Studio, Universidad de Cartagena
* **Fecha:** 2026-10-15
* **Estándar:** MADR 3.0.0

## Contexto y Definición del Problema

La inspección visual de la celda unitaria, la orientación de enlaces interatómicos y la verificación de simetrías espaciales son pasos críticos antes de lanzar cálculos costosos en un clúster de supercómputo. Tradicionalmente, los científicos recurren a programas externos de escritorio como VESTA o XCrySDen. Sin embargo, estas herramientas operan en ventanas separadas, no están integradas en el flujo de trabajo del editor, requieren exportar manualmente archivos temporales y con frecuencia presentan problemas de dependencias gráficas o emulación X11 sobre conexiones remotas.

## Factores de Decisión

* Integración en el IDE: La visualización debe ocurrir en el mismo espacio de trabajo donde el investigador edita sus archivos `.in` y `.cif`.
* Reactividad: Los cambios en los vectores de red o posiciones atómicas deben verse reflejados de inmediato.
* Portabilidad y multiplataforma sin requerir servidores X11 remotos ni software privativo instalado.
* Aceleración por hardware para manejar celdas unitarias y superceldas con cientos de átomos.

## Opciones Consideradas

1. **Lanzar software externo de escritorio (VESTA / XCrySDen / Avogadro):** Generar un archivo temporal y abrirlo con el binario local del software instalado.
2. **Generación de imágenes estáticas en el backend:** Renderizar imágenes PNG/SVG estáticas en el servidor Python mediante bibliotecas como Matplotlib y mostrarlas en el editor.
3. **Visor 3D WebGL Embebido con Three.js en Webview de VS Code:** Construir un componente de renderizado 3D acelerado por hardware dentro de un panel Webview aislado.

## Decisión Adoptada

Opción elegida: **Visor 3D WebGL Embebido con Three.js en Webview (Opción 3)**.

### Consecuencias Positivas

* **Ergonomía y Cero Cambio de Contexto:** El investigador inspecciona la estructura tridimensional directamente al lado de su archivo de parámetros de cálculo.
* **Aceleración por GPU Nativa:** Three.js aprovecha WebGL en el proceso Chromium de VS Code, ofreciendo controles orbitales suaves (rotación, zoom, paneo) a 60 FPS.
* **Interactividad Bidireccional:** Permite hacer clic sobre átomos individuales para consultar coordenadas, distancias de enlace interatómicas y ángulos de torsión.
* **Aislamiento de Seguridad:** El Webview se ejecuta en un contexto protegido con Content Security Policy (CSP), previniendo vulnerabilidades de inyección.

### Consecuencias Negativas

* **Consumo de Memoria GPU:** Sistemas con miles de átomos en superceldas masivas pueden impactar la memoria gráfica si no se implementa instanciación de mallas (*InstancedMesh*).
* **Complejidad de Empaquetado:** Requiere empaquetar el bundle JavaScript de Three.js y sus shaders dentro de los activos de la extensión (`media/viewer3d`).

## Pros y Contras de las Opciones

### Software Externo (VESTA)
* Bueno: Funcionalidades cristalográficas extremadamente maduras.
* Malo: Cero integración con el editor; no reacciona a los cambios en caliente; experiencia de usuario fragmentada; no siempre disponible en máquinas de estudiantes.

### Imágenes Estáticas en Backend
* Bueno: Fácil de implementar en Python.
* Malo: Cero interactividad 3D; imposible rotar la celda para inspeccionar átomos ocultos en planos perpendiculares; sobrecarga de transferir imágenes continuas.

### Three.js en Webview
* Bueno: Interactividad en tiempo real, renderizado GPU moderno, integración total con los temas visuales de VS Code y comunicación fluida vía IPC.
* Malo: Requiere implementar la lógica de radios atómicos (escala de van der Waals) y cálculo de enlaces en JavaScript o parsearlo desde el backend.
