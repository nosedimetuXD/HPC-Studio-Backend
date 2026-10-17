# ADR-0004: Soporte y Preset de Quantum Mobile sobre VirtualBox (SSH :2222)

* **Estado:** Aceptado
* **Decisores:** Equipo de Arquitectura de HPC Studio, Universidad de Cartagena
* **Fecha:** 2026-10-15
* **Estándar:** MADR 3.0.0

## Contexto y Definición del Problema

El aprendizaje de simulación cuántica de materiales y el desarrollo de scripts HPC suele presentar una barrera de entrada severa: los estudiantes e investigadores noveles no siempre cuentan con acceso inmediato a un supercomputador institucional con Slurm, y la compilación de Quantum ESPRESSO en sistemas operativos como Windows o macOS es un proceso propenso a fallos de librerías Fortran/BLAS/LAPACK.

El consorcio europeo MARVEL desarrolló la máquina virtual **Quantum Mobile**, basada en Linux Ubuntu, que incluye de forma preconfigurada y validada la suite completa de Quantum ESPRESSO, AiiDA, pseudopotenciales y un scheduler local. Se requiere que HPC Studio ofrezca soporte de primer nivel para esta plataforma, universalizando su uso formativo e investigativo sin obligar al usuario a configurar complejas redes virtuales.

## Factores de Decisión

* Democratización del acceso: Permitir que cualquier usuario en Windows, macOS o Linux ejecute cálculos cuánticos completos en su propia computadora.
* Entorno idéntico al clúster de producción: La VM expone el servicio SSH y utilidades Slurm idénticas a un clúster HPC real.
* Configuración cero (*Zero-Config*): El sistema debe ofrecer un preset preconfigurado para conectarse al reenvío de puertos estándar de VirtualBox.

## Opciones Consideradas

1. **Exclusividad para Supercomputadores Remotos:** Limitar la herramienta a clústeres reales en producción accesibles por internet.
2. **Contenedores Docker Locales:** Distribuir una imagen Docker con Quantum ESPRESSO y montarla mediante comandos locales.
3. **Preset Integrado para Quantum Mobile sobre VirtualBox:** Proveer soporte nativo en el gestor de clústeres para conectar por SSH al puerto NAT `127.0.0.1:2222` con credenciales predeterminadas de Quantum Mobile.

## Decisión Adoptada

Opción elegida: **Preset Integrado para Quantum Mobile (Opción 3)**, complementando el soporte para clústeres remotos.

### Consecuencias Positivas

* **Entorno de Prueba Seguro:** Los usuarios pueden probar scripts `sbatch` y flujos de trabajo completos sin consumir cuotas de horas de cómputo en supercomputadores institucionales.
* **Compatibilidad Universal:** VirtualBox funciona de manera estable en Windows, macOS y Linux. Al mapear el puerto de red `2222 -> 22` en modo NAT, el backend de HPC Studio trata a la máquina virtual exactamente igual que a un supercomputador remoto, reutilizando el mismo código SSH/SFTP sin ramas condicionales artificiales.
* **Facilidad Pedagógica:** Facilita talleres académicos universitarios en la Universidad de Cartagena donde los estudiantes pueden trabajar de forma autónoma sin conexión a internet constante.

### Consecuencias Negativas

* **Rendimiento de Cómputo Limitado:** La simulación se ejecuta bajo virtualización de CPU, restringida por la memoria RAM y núcleos físicos de la máquina anfitriona del estudiante.
* **Dependencia de VirtualBox:** El usuario debe descargar e importar la imagen OVA de Quantum Mobile en su hipervisor.

## Pros y Contras de las Opciones

### Exclusividad Remota
* Bueno: Menos configuraciones locales que soportar.
* Malo: Excluye a estudiantes y dificulta la docencia en universidades con cuotas de cómputo limitadas.

### Docker Local
* Bueno: Menor consumo de memoria que una máquina virtual completa.
* Malo: Docker en Windows y macOS introduce complejidades de reenvío de puertos y virtualización WSL2 que confunden a usuarios principiantes en ciencias de materiales.

### Preset Quantum Mobile
* Bueno: Experiencia completa de sistema operativo Linux idéntica a un nodo de supercómputo; preconfiguración validada científicamente por el consorcio MARVEL; reenvío limpio por puerto 2222.
* Malo: Descarga pesada del archivo OVA inicial (~5 GB).
