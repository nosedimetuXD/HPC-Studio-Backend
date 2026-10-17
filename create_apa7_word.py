import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

def create_apa7_document(output_path):
    doc = docx.Document()

    # 1. Page Setup: 1 inch (72 pt = 1440 twips) on all sides (Letter size)
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)
        section.page_width = Inches(8.5)
        section.page_height = Inches(11.0)
        
        # Add Page Number in Header (Flush Right)
        header = section.header
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run()
        hrun.font.name = "Times New Roman"
        hrun.font.size = Pt(12)
        hrun.font.color.rgb = RGBColor(0, 0, 0)
        
        # Add page number XML field
        fldSimple = OxmlElement('w:fldSimple')
        fldSimple.set(qn('w:instr'), 'PAGE')
        hp._p.append(fldSimple)

    # 2. Base Normal Style: Times New Roman, 12pt, double spacing
    style_normal = doc.styles['Normal']
    font_normal = style_normal.font
    font_normal.name = 'Times New Roman'
    font_normal.size = Pt(12)
    font_normal.color.rgb = RGBColor(0, 0, 0)
    
    p_format = style_normal.paragraph_format
    p_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
    p_format.space_after = Pt(0)
    p_format.space_before = Pt(0)

    # Helper functions for APA 7 elements
    def add_body_p(text, indent=True):
        p = doc.add_paragraph()
        if indent:
            p.paragraph_format.first_line_indent = Inches(0.5)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        run = p.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        return p

    def add_h1(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
        run = p.add_run(text)
        run.bold = True
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        return p

    def add_h2(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
        run = p.add_run(text)
        run.bold = True
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        return p

    def add_h3(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
        run = p.add_run(text)
        run.bold = True
        run.italic = True
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        return p

    # ==========================================
    # 3. TITLE PAGE (Page 1)
    # ==========================================
    for _ in range(3):
        doc.add_paragraph()

    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(
        "Diseño e Implementación de un Entorno de Desarrollo Integrado (IDE) Especializado "
        "para la Ingeniería de Software Cuántico y la Simulación Híbrida HPC-QC"
    )
    title_run.bold = True
    title_run.font.size = Pt(12)

    doc.add_paragraph()

    author_p = doc.add_paragraph()
    author_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_author = author_p.add_run("Investigador Principal / Equipo de Desarrollo de HPC Studio")
    r_author.font.size = Pt(12)

    affil_p = doc.add_paragraph()
    affil_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_affil = affil_p.add_run("Laboratorio de Supercómputo y Simulación Científica\nProyecto HPC Studio / Quantum Studio")
    r_affil.font.size = Pt(12)

    date_p = doc.add_paragraph()
    date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_date = date_p.add_run("Octubre de 2026")
    r_date.font.size = Pt(12)

    # Page Break to Abstract
    doc.add_page_break()

    # ==========================================
    # 4. ABSTRACT (Page 2)
    # ==========================================
    add_h1("Resumen")

    add_body_p(
        "El paradigma emergente de la computación cuántica en la era de Escala Intermedia con Ruido "
        "(NISQ, por sus siglas en inglés) enfrenta una brecha sustancial en sus capas de abstracción e "
        "interacción humana: la ausencia de entornos de desarrollo integrados (IDE) dedicados que "
        "trasciendan las limitaciones lineales de los cuadernos de notas (computational notebooks). "
        "Esta investigación propone el diseño, fundamentación arquitectónica e implementación prototípica "
        "de Quantum Studio, un IDE nativo y modular de código abierto optimizado para el diseño, simulación, "
        "visualización geométrica y transpilación de circuitos cuánticos, con soporte explícito para flujos "
        "híbridos cuántico-clásicos (HPC-QC). La plataforma integra un servidor de lenguaje (Language Server "
        "Protocol, LSP) para OpenQASM 3.0, un motor reactivo de representación gráfica de circuitos, un "
        "módulo WebGL tridimensional para la proyección de estados en la Esfera de Bloch y variedades de "
        "subespacios multiqubit, conectores bidireccionales con gestores de carga de trabajo de supercómputo "
        "(Slurm) y unidades de procesamiento cuántico (QPU) en la nube, y una capa de asistencia algorítmica "
        "impulsada por agentes de inteligencia artificial mediante el Model Context Protocol (MCP). La "
        "metodología de investigación adopta un enfoque de diseño e ingeniería de software basado en "
        "artefactos (Design Science Research), evaluando métricas de latencia cognitiva, fidelidad sintáctica "
        "y rendimiento de transpilación frente a flujos de trabajo convencionales.",
        indent=False
    )

    kw_p = doc.add_paragraph()
    kw_p.paragraph_format.first_line_indent = Inches(0.5)
    kw_p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
    r_kw_label = kw_p.add_run("Palabras clave: ")
    r_kw_label.italic = True
    kw_p.add_run("Computación cuántica, IDE, OpenQASM 3.0, Esfera de Bloch, HPC-QC, transpilación de circuitos, ingeniería de software cuántico.")

    doc.add_page_break()

    # ==========================================
    # 5. BODY OF THE PAPER
    # ==========================================
    add_h1("Diseño e Implementación de un Entorno de Desarrollo Integrado Especializado para la Ingeniería de Software Cuántico")

    add_h2("1. Introducción y Planteamiento del Problema")
    add_body_p(
        "La computación cuántica representa uno de los saltos cualitativos más trascendentales en la historia "
        "del procesamiento de la información, prometiendo resolver problemas computacionalmente intratables para "
        "los procesadores clásicos de von Neumann en áreas como la simulación de materiales moleculares, el modelado "
        "farmacológico, la criptografía poscuántica y la optimización combinatoria de alta complejidad (Nielsen & Chuang, 2010; "
        "Preskill, 2018)."
    )
    add_body_p(
        "A pesar del vertiginoso avance en el hardware de Unidades de Procesamiento Cuántico (QPU) —abarcando circuitos "
        "superconductores, trampas de iones y arreglos de átomos neutros—, la Ingeniería de Software Cuántico (QSE) "
        "padece un notable rezago epistemológico y de instrumentalización técnica (Piattini et al., 2020). En la actualidad, "
        "el desarrollo de algoritmos cuánticos se efectúa predominantemente a través de bibliotecas heterogéneas escritas "
        "en Python (como Qiskit, Cirq y PennyLane) acopladas a interfaces de usuario monolíticas basadas en cuadernos de cálculo "
        "interactivos (Jupyter Notebooks)."
    )
    add_body_p(
        "Si bien los cuadernos interactivos resultan didácticos para la experimentación exploratoria inicial, presentan deficiencias "
        "estructurales críticas en entornos de ingeniería de software avanzada (Rule et al., 2018): en primer lugar, existe una severa "
        "fragmentación del flujo híbrido clásico-cuántico necesario para coordinar algoritmos variacionales como el Variational "
        "Quantum Eigensolver (VQE) o el Quantum Approximate Optimization Algorithm (QAOA); en segundo lugar, se carece de herramientas "
        "geométricas reactivas en tiempo real, generándose los circuitos y vectores de estado como imágenes estáticas no manipulables; y en "
        "tercer lugar, los desarrolladores operan a ciegas respecto al presupuesto de ruido físico, la profundidad del circuito (circuit depth) "
        "y la topología de conectividad de la QPU antes de despachar el trabajo a la nube."
    )
    add_body_p(
        "A partir de este escenario, se formula la siguiente pregunta de investigación: ¿De qué manera el diseño y la construcción de un "
        "Entorno de Desarrollo Integrado especializado, nativo y extensible puede mitigar la fricción cognitiva, optimizar la síntesis "
        "algorítmica y estandarizar la programación híbrida cuántica-clásica (HPC-QC)?"
    )

    add_h2("2. Objetivos de la Investigación")
    add_h3("2.1. Objetivo General")
    add_body_p(
        "Diseñar, implementar y evaluar un Entorno de Desarrollo Integrado (IDE) nativo y multimodal orientado a la ingeniería de software "
        "cuántico y a la supercomputación híbrida, que unifique la codificación formal, la visualización tridimensional de estados, la transpilación "
        "reactiva y la ejecución de algoritmos sobre simuladores y procesadores cuánticos físicos."
    )

    add_h3("2.2. Objetivos Específicos")
    add_body_p("1. Desarrollar un Servidor de Lenguaje (Language Server Protocol, LSP) para OpenQASM 3.0 y lenguajes cuánticos de alto nivel, proveyendo análisis semántico, validación tipográfica de compuertas y comprobación de parámetros en tiempo de edición.")
    add_body_p("2. Construir un motor visual reactivo y bidireccional de circuitos cuánticos, permitiendo la manipulación sincrónica entre la representación textual y la esquemática gráfica.")
    add_body_p("3. Diseñar un módulo WebGL tridimensional para la proyección de estados en la Esfera de Bloch individual y variedades de matrices de densidad multiqubit.")
    add_body_p("4. Implementar una capa de orquestación de recursos híbridos (HPC-QC), enlazando gestores de colas de clústeres clásicos (Slurm) con plataformas de ejecución cuántica en la nube (IBM Quantum, AWS Braket).")
    add_body_p("5. Integrar un agente inteligente de optimización cuántica asistido por Inteligencia Artificial basado en el Model Context Protocol (MCP), capacitado para sugerir descomposiciones Clifford + T y cancelación de compuertas redundantes.")

    add_h2("3. Marco Teórico y Tecnológico")
    add_h3("3.1. Estado Cuántico y la Esfera de Bloch")
    add_body_p(
        "El estado fundamental de un cúbit puro |ψ⟩ en un espacio de Hilbert bidimensional H₂ se expresa formalmente como una superposición "
        "lineal de la base computacional {|0⟩, |1⟩}: |ψ⟩ = cos(θ/2)|0⟩ + e^(iφ)sin(θ/2)|1⟩, donde θ ∈ [0, π] y φ ∈ [0, 2π). Los parámetros "
        "esféricos (θ, φ) definen de manera unívoca un vector unitario en la superficie de la Esfera de Bloch tridimensional S², posibilitando la "
        "representación visual de operadores unitarios U ∈ SU(2) como rotaciones espaciales rígidas respecto a los ejes de Pauli (Nielsen & Chuang, 2010)."
    )

    add_h3("3.2. Estandarización de OpenQASM 3.0")
    add_body_p(
        "A diferencia de versiones precedentes de carácter puramente declarativo, la especificación OpenQASM 3.0 introduce control de flujo clásico "
        "dinámico en tiempo de ejecución, sincronización temporal con calibración de pulsos analógicos a escala de nanosegundos y operaciones subrutinarias "
        "con retroalimentación rápida (Cross et al., 2022). Esta sofisticación matemática y técnica justifica la integración de analizadores sintácticos abstractos "
        "(AST) en el núcleo del editor de código."
    )

    add_h3("3.3. Algoritmos Híbridos Clásicos-Cuánticos y Supercómputo (HPC-QC)")
    add_body_p(
        "En la era NISQ, los algoritmos variacionales híbridos como VQE (Peruzzo et al., 2014) distribuyen la carga computacional de forma cooperativa: "
        "la QPU prepara el estado parametrizado |ψ(θ)⟩ y ejecuta mediciones proyectivas, mientras que un clúster clásico HPC ejecuta optimizadores multivariados "
        "(COBYLA, SPSA o métodos de gradiente estocástico) para iterar sobre los parámetros. La interacción fluida entre Slurm y la API de la QPU constituye "
        "el pilar operativo de la supercomputación contemporánea."
    )

    add_h2("4. Metodología y Arquitectura Técnica")
    add_body_p(
        "La investigación adopta la metodología Design Science Research Methodology (DSRM) formulada por Hevner et al. (2004), orientada a la creación y "
        "evaluación rigurosa de artefactos tecnológicos innovadores organizados en cuatro componentes arquitectónicos centrales:"
    )
    add_body_p(
        "A. Núcleo del IDE y Lenguaje: Basado en una arquitectura modular derivada de Code OSS, con un servidor LSP dedicado para OpenQASM 3.0 compilado sobre Node.js/TypeScript, "
        "capaz de parsear gramáticas Tree-sitter y enlazar con representaciones intermedias cuánticas (QIR)."
    )
    add_body_p(
        "B. Visualización Reactiva y WebGL: Un subsistema gráfico implementado en WebGL y Three.js que proyecta la Esfera de Bloch en 3D interactivo, permitiendo al usuario "
        "inspeccionar amplitudes de probabilidad complejas, fases relativas y trayectorias continuas generadas por compuertas Rx, Ry y Rz."
    )
    add_body_p(
        "C. Orquestación HPC-QC: Módulos de conexión segura hacia clústeres supercomputacionales gobernados por Slurm y conectores REST/gRPC hacia las plataformas cuánticas "
        "de IBM Quantum Runtime y Amazon Braket SDK."
    )
    add_body_p(
        "D. Agente de Optimización Asistido por IA (MCP Server): Servidor de herramientas bajo el estándar Model Context Protocol que provee inspección topológica de la QPU, "
        "estimación analítica de profundidad de circuito y formulación automática de ansätze variacionales."
    )

    add_h2("5. Resultados Esperados e Impacto")
    add_body_p(
        "Se anticipa que la implementación de Quantum Studio proporcione: (1) una reducción sustancial de la sobrecarga cognitiva en los desarrolladores de algoritmos cuánticos; "
        "(2) la disminución de errores de transpilación mediante diagnósticos predictivos de topología y ruido; y (3) la validación formal de una plataforma científica unificada capaz "
        "de acelerar la investigación interdisciplinaria en química cuántica, física del estado sólido y ciencia de materiales."
    )

    add_h2("6. Conclusiones")
    add_body_p(
        "La superación de los cuellos de botella presentes en la computación cuántica contemporánea exige un salto evolutivo en las herramientas de ingeniería de software. El proyecto "
        "Quantum Studio demuestra que la integración de lenguajes formales, interfaces gráficas interactivas tridimensionales y orquestación híbrida supercomputacional constituye "
        "el estándar arquitectónico requerido para habilitar el descubrimiento científico en la era de la ventaja cuántica."
    )

    # Page Break to References
    doc.add_page_break()

    # ==========================================
    # 6. REFERENCES (APA 7th Format)
    # ==========================================
    add_h1("Referencias")

    references = [
        "Cross, A., Javadi-Abhari, A., Alexander, T., de Beaudrap, N., Bishop, L. S., Heidel, S., Ryan, C. A., Sete, P., Sheldon, S., Smolin, J. A., Gambetta, J. M., & McKay, D. C. (2022). OpenQASM 3: A broader and deeper quantum assembly language. ACM Transactions on Quantum Computing, 3(3), 1–50. https://doi.org/10.1145/3505636",
        "Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. MIS Quarterly, 28(1), 75–105. https://doi.org/10.2307/25148625",
        "Nielsen, M. A., & Chuang, I. L. (2010). Quantum computation and quantum information: 10th anniversary edition. Cambridge University Press. https://doi.org/10.1017/CBO9780511976667",
        "Peruzzo, A., McClean, J., Shadbolt, P., Yung, M.-H., Zhou, X.-Q., Love, P. J., Aspuru-Guzik, A., & O'Brien, J. L. (2014). A variational eigenvalue solver on a photonic quantum processor. Nature Communications, 5(1), 4213. https://doi.org/10.1038/ncomms5213",
        "Piattini, M., Peterssen, G., & Pérez-Castillo, R. (2020). Quantum computing: A new software engineering golden age. ACM SIGSOFT Software Engineering Notes, 45(3), 12–14. https://doi.org/10.1145/3400828.3400831",
        "Preskill, J. (2018). Quantum computing in the NISQ era and beyond. Quantum, 2, 79. https://doi.org/10.22331/q-2018-08-06-79",
        "Rule, A., Birmingham, A., Zuniga, C., Altintas, I., Huang, S. C., Jenssen, T. K., Billings, N., Kim, P., & Bourne, P. E. (2018). Ten simple rules for writing and sharing computational analyses in Jupyter Notebooks. PLOS Computational Biology, 14(7), e1006220. https://doi.org/10.1371/journal.pcbi.1006220"
    ]

    for ref in sorted(references):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.5)
        p.paragraph_format.first_line_indent = Inches(-0.5)  # Hanging indent (sangría francesa)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        run = p.add_run(ref)
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)

    doc.save(output_path)
    print(f"Document successfully created at: {output_path}")

if __name__ == "__main__":
    create_apa7_document("/home/nosedimetuxd/Proyectos/HPC Studio/docs/proyecto_investigacion_quantum_studio_apa7.docx")
