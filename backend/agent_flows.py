"""
Flujos de agentes: varios modelos pequeños en cadena, cada uno en lo suyo.

La idea de fondo es que un modelo de 7B no es peor que uno de 32B en todo — es peor
en algunas cosas y prácticamente igual en otras. Extraer una definición literal de un
párrafo no requiere razonar: requiere leer con cuidado y copiar bien. Diseñar un
ejercicio progresivo sí requiere razonar. Encadenar varios pasos pequeños, cada uno
con el modelo adecuado y una sola tarea, rinde más que pedirle todo de golpe a un
modelo grande que no te cabe en la GPU.

Lo que hace que esto funcione y no sea un juguete:

  · CADA PASO VE LO QUE NECESITA, no todo. Un paso que solo corrige no necesita el
    libro entero; pasárselo desperdicia ventana de contexto y lo distrae.
  · LOS FORMATOS SE COMPRUEBAN. Si un paso debe devolver JSON y no lo hace, se le
    pide otra vez señalando el fallo concreto, no se propaga basura al siguiente.
  · HAY BUCLE DE CRÍTICA. Un paso puede revisar a otro y devolverle el trabajo. Es
    el patrón que más mejora la calidad, y es justo lo que un modelo solo no hace.
  · SE CUENTA EL COSTE DE CAMBIAR DE MODELO. Con 6 GB de VRAM solo cabe uno a la
    vez: cada cambio en la cadena es una recarga desde disco. El flujo te lo dice
    antes de ejecutarlo, y ordenar los pasos para agrupar modelos es gratis.
  · QUEDA EL HISTORIAL COMPLETO. Prompt exacto, salida, modelo y tiempo de cada
    paso. Sin eso, un flujo que da un mal resultado es imposible de arreglar: no
    sabes cuál de los cinco agentes lo estropeó.
"""

import os
import re
import json
import queue
import time
import threading
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

MAX_FLUJOS = 200
MAX_HISTORIAL = 100
MAX_PASOS = 12
MAX_VUELTAS_TOTALES = 6          # tope duro de reintentos por ejecución


# ===========================================================================
# Catálogo de modelos
# ===========================================================================

# Tamaños aproximados en Q4_K_M. Verifícalos con `ollama pull`: la biblioteca de
# Ollama cambia, y lo que aquí dice 4,7 GB puede no ser lo que descargues hoy.
#
# `vram_gb` es lo que ocupa el modelo. Súmale la caché KV (unos 0,25 GB con 4096
# de contexto en un 7B) para saber si entra de verdad en tu tarjeta.
# Tamaños VERIFICADOS contra el registro de Ollama, no de memoria. `vram_gb` es lo
# que ocupa el modelo; súmale la caché KV (~0,3 GB con 4096 de contexto en un 7B)
# para saber si entra de verdad.
#
# `piensa`: el modelo razona en voz alta antes de responder. Eso es excelente para
# criticar y planificar, y estorba para extraer, porque el bloque de pensamiento
# ensucia la salida y se come la ventana. En Qwen3 se puede APAGAR por paso, que es
# lo que lo hace el más versátil de esta lista; en los R1 destilados no.
MODELOS = {
    # ---------------------------------------------------------------
    # Qwen3 — la familia más reciente que entra en una tarjeta pequeña.
    # No existe un 9B: las tallas son 0.6, 1.7, 4, 8 y 14 (más una MoE de 30B).
    # ---------------------------------------------------------------
    "qwen3:8b": {
        "vram_gb": 5.2, "familia": "Qwen3", "razona": 5, "piensa": "conmutable",
        "fuerte_en": ["razonar", "criticar", "verificar", "redactar", "extraer",
                      "corregir"],
        "nota": "El más capaz que entra entero en 6 GB. Piensa en voz alta cuando le "
                "conviene y calla cuando no, así que sirve para toda la cadena. Va "
                "justo de memoria: deja poco margen para contexto largo.",
    },
    "qwen3:4b": {
        "vram_gb": 2.5, "familia": "Qwen3", "razona": 4, "piensa": "conmutable",
        "fuerte_en": ["razonar", "criticar", "extraer", "redactar", "corregir"],
        "nota": "Razona sorprendentemente bien para su tamaño y deja 3,5 GB libres: "
                "es el que permite tener dos modelos cargados a la vez.",
    },
    "qwen3:1.7b": {
        "vram_gb": 1.4, "familia": "Qwen3", "razona": 3, "piensa": "conmutable",
        "fuerte_en": ["clasificar", "extraer"],
        "nota": "Para pasos mecánicos. Con pensamiento apagado va muy rápido.",
    },
    "qwen3:0.6b": {
        "vram_gb": 0.5, "familia": "Qwen3", "razona": 2, "piensa": "conmutable",
        "fuerte_en": ["clasificar"],
        "nota": "Filtro previo barato: clasificar, etiquetar, decidir si algo merece "
                "un modelo mayor.",
    },
    "qwen3:14b": {
        "vram_gb": 9.3, "familia": "Qwen3", "razona": 5, "piensa": "conmutable",
        "fuerte_en": ["razonar", "criticar", "verificar"],
        "nota": "No cabe en 6 GB: unos 4 GB irían a RAM y sería bastante más lento. "
                "Sirve para UN paso de revisión final sobre un texto ya corto.",
    },
    "qwen3:30b-a3b": {
        "vram_gb": 18.2, "familia": "Qwen3", "razona": 5, "piensa": "conmutable",
        "fuerte_en": ["razonar", "criticar", "verificar", "redactar"],
        "nota": "MoE oficial de Qwen3 (30B totales, 3.3B activos por token). Inferencia "
                "muy rápida con pensamiento conmutable; requiere ~18 GB de memoria.",
    },

    # --- Qwen2.5: menos capaz razonando, más disciplinado con el JSON -----
    "qwen2.5:7b": {
        "vram_gb": 4.7, "familia": "Qwen2.5", "razona": 3, "piensa": "no",
        "fuerte_en": ["extraer", "redactar", "razonar", "corregir"],
        "nota": "Instruct general. Sigue instrucciones y copia literal muy bien, sin "
                "bloque de pensamiento que estorbe.",
    },
    "qwen2.5-coder:7b": {
        "vram_gb": 4.7, "familia": "Qwen2.5", "razona": 3, "piensa": "no",
        "fuerte_en": ["programar", "extraer", "corregir"],
        "nota": "Para código y libros de programación. Medido en Prig: 100 % de citas "
                "verificadas con formato JSON forzado.",
    },
    "qwen2.5-coder:3b": {
        "vram_gb": 1.9, "familia": "Qwen2.5", "razona": 2, "piensa": "no",
        "fuerte_en": ["programar", "clasificar"],
        "nota": "Código en poco espacio.",
    },
    "qwen2.5:3b": {
        "vram_gb": 1.9, "familia": "Qwen2.5", "razona": 2, "piensa": "no",
        "fuerte_en": ["extraer", "clasificar"],
        "nota": "Pasos mecánicos dejando sitio a otro modelo.",
    },
    "qwen2.5-coder:1.5b": {
        "vram_gb": 1.0, "familia": "Qwen2.5", "razona": 1, "piensa": "no",
        "fuerte_en": ["clasificar"],
        "nota": "Solo para tareas de una línea.",
    },

    # --- Razonadores destilados: piensan siempre, no se puede apagar ------
    "deepseek-r1:8b": {
        "vram_gb": 5.2, "familia": "R1 destilado", "razona": 5, "piensa": "siempre",
        "fuerte_en": ["razonar", "criticar", "verificar"],
        "nota": "DeepSeek-R1-0528 destilado sobre Qwen3 8B (la etiqueta 8b de Ollama). "
                "Entra en 6 GB de VRAM",
    },
    "deepseek-r1:7b": {
        "vram_gb": 4.7, "familia": "R1 destilado", "razona": 5, "piensa": "siempre",
        "fuerte_en": ["razonar", "criticar", "verificar"],
        "nota": "Igual que el de 8B pero sobre Qwen. Prueba los dos: en cada equipo "
                "suele ir mejor uno.",
    },
    "deepseek-r1:1.5b": {
        "vram_gb": 1.1, "familia": "R1 destilado", "razona": 3, "piensa": "siempre",
        "fuerte_en": ["razonar"],
        "nota": "Razona por encima de su tamaño, pero gasta muchos tokens pensando.",
    },

    # --- Otras familias que entran enteras -------------------------------
    "gemma3:4b": {
        "vram_gb": 3.3, "familia": "Gemma 3", "razona": 3, "piensa": "no",
        "fuerte_en": ["redactar", "extraer"],
        "nota": "Escribe muy bien en castellano para lo que ocupa.",
    },
    "gemma2:9b": {
        "vram_gb": 5.4, "familia": "Gemma 2", "razona": 3, "piensa": "no",
        "fuerte_en": ["redactar", "razonar"],
        "nota": "Bueno explicando en castellano. Muy justo de espacio.",
    },
    "llama3.1:8b": {
        "vram_gb": 4.9, "familia": "Llama 3.1", "razona": 3, "piensa": "no",
        "fuerte_en": ["redactar", "razonar"],
        "nota": "Explicaciones largas con naturalidad. Menos disciplinado con el JSON.",
    },
    "llama3.2:3b": {
        "vram_gb": 2.0, "familia": "Llama 3.2", "razona": 2, "piensa": "no",
        "fuerte_en": ["redactar", "clasificar"],
        "nota": "Ligero y rápido para pasos de redacción corta.",
    },
    "granite3.3:8b": {
        "vram_gb": 4.9, "familia": "Granite 3.3", "razona": 3, "piensa": "no",
        "fuerte_en": ["extraer", "razonar", "corregir"],
        "nota": "Pensado para tareas de empresa: muy regular siguiendo formatos.",
    },
    "phi4-mini": {
        "vram_gb": 2.5, "familia": "Phi-4", "razona": 3, "piensa": "no",
        "fuerte_en": ["razonar", "verificar"],
        "nota": "Fuerte en razonamiento matemático para su tamaño.",
    },
    "mistral:7b": {
        "vram_gb": 4.4, "familia": "Mistral", "razona": 2, "piensa": "no",
        "fuerte_en": ["redactar"],
        "nota": "Rápido y correcto, sin destacar en nada concreto.",
    },
    "exaone3.5:7.8b": {
        "vram_gb": 4.8, "familia": "EXAONE 3.5", "razona": 3, "piensa": "no",
        "fuerte_en": ["razonar", "extraer"],
        "nota": "Buena relación entre tamaño y capacidad; menos probado en castellano.",
    },
    "olmo2:7b": {
        "vram_gb": 4.5, "familia": "OLMo 2", "razona": 3, "piensa": "no",
        "fuerte_en": ["razonar", "redactar"],
        "nota": "Completamente abierto, datos de entrenamiento incluidos.",
    },

    # --- No caben en 6 GB: reparten con la CPU ----------------------------
    "phi4": {
        "vram_gb": 9.1, "familia": "Phi-4", "razona": 4, "piensa": "no",
        "fuerte_en": ["razonar", "verificar"],
        "nota": "Fuerte en matemáticas, pero no entra: unos 3,5 GB irían a RAM.",
    },
    "qwen2.5:14b": {
        "vram_gb": 9.0, "familia": "Qwen2.5", "razona": 4, "piensa": "no",
        "fuerte_en": ["razonar", "criticar", "redactar"],
        "nota": "No cabe en 6 GB. Para un paso de revisión final, no para un libro.",
    },
    "deepseek-r1:14b": {
        "vram_gb": 9.0, "familia": "R1 destilado", "razona": 5, "piensa": "siempre",
        "fuerte_en": ["criticar", "verificar"],
        "nota": "El mejor revisor de la lista, pero reparte con la CPU.",
    },
    "gemma3:12b": {
        "vram_gb": 8.1, "familia": "Gemma 3", "razona": 4, "piensa": "no",
        "fuerte_en": ["redactar", "razonar"],
        "nota": "Muy bueno redactando, pero no entra entero.",
    },
    "mistral-nemo:12b": {
        "vram_gb": 7.1, "familia": "Mistral", "razona": 3, "piensa": "no",
        "fuerte_en": ["redactar", "razonar"],
        "nota": "Ventana de contexto muy amplia. No entra entero.",
    },

    # --- Razonadores, mezclas y arquitecturas MoE comunitarias y avanzadas ---
    # Nombres verificados contra su registro (ollama.com o Hugging Face). Los que había
    # antes con nombres inventados (olmoe:1b-7b, phi3.5-moe:latest…) daban 404 al
    # descargar; se sustituyeron por su equivalente real o se quitaron.
    "hf.co/bartowski/OLMoE-1B-7B-0924-Instruct-GGUF:Q4_K_M": {
        "vram_gb": 4.2, "familia": "OLMoE", "razona": 3, "piensa": "no",
        "fuerte_en": ["extraer", "redactar", "clasificar"],
        "nota": "MoE 100 % abierto de Allen AI (7B totales, 1B activos), desde Hugging Face. "
                "Entra entero en 6 GB de VRAM y genera muy rápido.",
    },
    "qwen3-coder:30b": {
        "vram_gb": 18.6, "familia": "Qwen3-Coder MoE", "razona": 4, "piensa": "no",
        "fuerte_en": ["programar", "corregir", "verificar"],
        "nota": "MoE de código de Qwen (30B totales, 3,3B activos). No entra en 6 GB: se "
                "reparte con la RAM, pero al activar pocos parámetros sigue siendo rápido.",
    },
    "dolphin3:8b": {
        "vram_gb": 4.9, "familia": "Dolphin 3", "razona": 3, "piensa": "no",
        "fuerte_en": ["redactar", "razonar"],
        "nota": "Dolphin 3.0 sobre Llama 3.1 8B: sigue instrucciones con pocos rechazos. "
                "Entra en 6 GB.",
    },
    "hf.co/RichardErkhov/Qwen_-_Qwen1.5-MoE-A2.7B-Chat-gguf:Q4_K_M": {
        "vram_gb": 9.5, "familia": "Qwen1.5 MoE", "razona": 3, "piensa": "no",
        "fuerte_en": ["extraer", "redactar", "programar"],
        "nota": "MoE de Qwen (14B totales, 2,7B activos), desde Hugging Face. Se reparte "
                "con la RAM en 6 GB.",
    },
    "deepseek-coder-v2:16b": {
        "vram_gb": 8.9, "familia": "DeepSeek Coder", "razona": 4, "piensa": "no",
        "fuerte_en": ["programar", "corregir", "extraer"],
        "nota": "Versión Lite de DeepSeek-Coder-V2 (MoE 16B totales, 2.4B activos). "
                "Excelente para código, matemáticas y lógica.",
    },
    "deepseek-coder-v2:lite": {
        "vram_gb": 8.9, "familia": "DeepSeek Coder", "razona": 4, "piensa": "no",
        "fuerte_en": ["programar", "corregir", "extraer"],
        "nota": "Alias de DeepSeek-Coder-V2 16B Lite.",
    },
    "qwen3.6:35b-a3b": {
        "vram_gb": 22.6, "familia": "Qwen3.6 MoE", "razona": 5, "piensa": "conmutable",
        "fuerte_en": ["razonar", "criticar", "verificar", "redactar", "programar"],
        "nota": "MoE de 35B totales y 3B activos, con visión. Requiere unos 23 GB entre "
                "RAM y VRAM.",
    },
    "hf.co/bartowski/Phi-3.5-MoE-instruct-GGUF:Q4_K_M": {
        "vram_gb": 25.4, "familia": "Phi-3.5 MoE", "razona": 5, "piensa": "no",
        "fuerte_en": ["razonar", "verificar", "programar", "redactar"],
        "nota": "Phi-3.5 MoE de Microsoft (42B totales, 6,6B activos), desde Hugging Face. "
                "Requiere unos 25 GB entre RAM y VRAM.",
    },
    "mixtral:8x7b": {
        "vram_gb": 26.0, "familia": "Mixtral", "razona": 4, "piensa": "no",
        "fuerte_en": ["redactar", "razonar", "extraer", "programar"],
        "nota": "El MoE clásico de Mistral AI (47B totales, 13B activos). Excelente calidad "
                "general; requiere ~26 GB de memoria compartida.",
    },
}

# Familias que salieron después de cierta versión de Ollama y que una anterior no
# puede ni descargar: el registro responde 412 con un mensaje que no dice qué
# versión tienes. Verificado contra el registro; si una familia no está aquí, es
# que funciona con cualquier versión razonablemente reciente.
OLLAMA_MINIMO = {
    "qwen3": "0.6.6",
    "gemma3": "0.6.0",
    "granite3.3": "0.6.0",
    "qwen3-coder": "0.11.0",
}


def version_suficiente(actual: str, minima: str) -> bool:
    """ Compara versiones tipo 0.5.7 sin depender de nada externo """
    def partes(v):
        return [int(x) for x in re.findall(r"\d+", v or "")][:3] or [0]
    a, m = partes(actual), partes(minima)
    a += [0] * (3 - len(a))
    m += [0] * (3 - len(m))
    return a >= m


def ollama_necesario(modelo: str) -> Optional[str]:
    """ Versión mínima de Ollama para este modelo, si la tiene """
    familia = (modelo or "").split(":")[0]
    return OLLAMA_MINIMO.get(familia)


# Modelos de embeddings: no generan texto, sirven para elegir qué se le da al
# generador. Van en CPU, así que no compiten por la VRAM.
MODELOS_EMBEDDING = {
    "bge-m3": {
        "vram_gb": 1.2, "familia": "BGE-M3", "multilingue": True,
        "nota": "Multilingüe de verdad. Medido en Prig: 6 aciertos de 7 con preguntas "
                "en castellano, contra 4 de 7 de nomic-embed-text.",
    },
    "nomic-embed-text": {
        "vram_gb": 0.3, "familia": "Nomic", "multilingue": False,
        "nota": "Ligero, pero flojo en castellano: las mismas preguntas traducidas al "
                "inglés le suben de 4 a 6 aciertos de 7.",
    },
}

def detectar_vram_gb(por_defecto: float = 6.0) -> float:
    """ VRAM de la GPU, para saber qué modelos caben de verdad.

    Sin esto habría que suponer un tamaño, y suponer de más es peor que suponer de
    menos: ofrecer en el desplegable un modelo que no entra solo sirve para que la
    ejecución muera a mitad de un flujo de cinco pasos.
    """
    try:
        import subprocess
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        mb = max(int(x) for x in r.stdout.split() if x.strip().isdigit())
        return round(mb / 1024, 1)
    except Exception:
        return por_defecto


VRAM_TIPICA_GB = detectar_vram_gb()


# ===========================================================================
# Roles
# ===========================================================================

# Cada rol lleva su instrucción de sistema. No son adornos: encierran lo que
# distingue a un buen paso de ese tipo, y son lo que evita que cinco agentes
# hagan cinco veces lo mismo con distinto nombre.
ROLES = {
    "extraer": {
        "nombre": "Extractor",
        "icono": "fa-highlighter",
        "formato": "json",
        "temperatura": 0.1,
        "sistema": (
            "Extraes información de un texto. Trabajas SOLO con lo que el texto dice: "
            "no completas con lo que sabes, no interpretas, no resumes con tus palabras "
            "cuando puedes citar. Cada dato que devuelves lleva la frase literal del "
            "texto que lo respalda, copiada carácter a carácter. Si algo no está en el "
            "texto, no está. Devuelves únicamente JSON válido."
        ),
        "ayuda": "Lee y saca datos citando literalmente. Modelo instruct, nunca uno "
                 "que razone en voz alta.",
    },
    "razonar": {
        "nombre": "Analista",
        "icono": "fa-brain",
        "formato": "texto",
        "temperatura": 0.4,
        "sistema": (
            "Analizas en profundidad. Antes de concluir, expones el razonamiento paso "
            "a paso: qué se sabe, qué se deduce y de qué. Distingues siempre lo que "
            "está respaldado por el material de lo que es inferencia tuya, y dices "
            "cuál es cuál. Prefieres una conclusión matizada y honesta a una rotunda "
            "y cómoda."
        ),
        "ayuda": "Analiza, deduce y conecta. Aquí es donde un modelo de razonamiento "
                 "gana de verdad.",
    },
    "criticar": {
        "nombre": "Revisor",
        "icono": "fa-magnifying-glass",
        "formato": "json",
        "temperatura": 0.2,
        "sistema": (
            "Revisas el trabajo de otro agente buscando fallos concretos. No reescribes "
            "ni elogias: señalas. Cada problema que encuentras lleva dónde está, por "
            "qué es un problema y qué habría que hacer. Si no encuentras nada serio, lo "
            "dices claramente en lugar de inventar objeciones menores para justificarte. "
            "Devuelves únicamente JSON válido con la forma "
            '{"aprobado": true|false, "problemas": [{"donde": "...", "que": "...", '
            '"arreglo": "..."}]}.'
        ),
        "ayuda": "Busca fallos en el paso anterior. Puede devolverle el trabajo para "
                 "que lo rehaga.",
    },
    "corregir": {
        "nombre": "Corrector",
        "icono": "fa-wrench",
        "formato": "texto",
        "temperatura": 0.2,
        "sistema": (
            "Recibes un trabajo y una lista de problemas detectados. Arreglas "
            "exactamente esos problemas y nada más: no reescribes lo que ya estaba "
            "bien, no cambias el estilo, no añades secciones. Devuelves el trabajo "
            "completo ya corregido, no un parche ni una lista de cambios."
        ),
        "ayuda": "Aplica las correcciones del revisor sin rehacer lo que funcionaba.",
    },
    "programar": {
        "nombre": "Programador",
        "icono": "fa-code",
        "formato": "texto",
        "temperatura": 0.2,
        "sistema": (
            "Escribes código que se ejecuta. Nada de pseudocódigo ni de funciones que "
            "das por hechas: si hace falta un import, lo pones. El código es legible "
            "sin comentarios que expliquen lo obvio, y los casos límite se tratan o se "
            "señalan explícitamente."
        ),
        "ayuda": "Escribe código ejecutable. Usa un modelo coder.",
    },
    "verificar": {
        "nombre": "Verificador",
        "icono": "fa-check-double",
        "formato": "json",
        "temperatura": 0.0,
        "sistema": (
            "Compruebas afirmaciones concretas: fórmulas, cálculos, pasos de una "
            "derivación, correspondencia entre lo dicho y lo citado. Verificas una por "
            "una y dices cuál falla y por qué. No opinas sobre el estilo. Devuelves "
            "únicamente JSON válido con la forma "
            '{"correctas": [...], "incorrectas": [{"afirmacion": "...", "fallo": "..."}]}.'
        ),
        "ayuda": "Comprueba fórmulas y derivaciones. Temperatura cero.",
    },
    "redactar": {
        "nombre": "Redactor",
        "icono": "fa-feather",
        "formato": "texto",
        "temperatura": 0.5,
        "sistema": (
            "Escribes para alguien que está aprendiendo. Empiezas por la idea antes que "
            "por la formalización, usas ejemplos concretos antes que definiciones "
            "generales, y cuando algo es difícil dices que es difícil en lugar de "
            "disimularlo. No repites el enunciado de la pregunta ni anuncias lo que vas "
            "a decir: lo dices."
        ),
        "ayuda": "Convierte el análisis en una explicación que se entienda.",
    },
    "clasificar": {
        "nombre": "Clasificador",
        "icono": "fa-tags",
        "formato": "json",
        "temperatura": 0.0,
        "sistema": (
            "Clasificas y etiquetas. Respondes con la etiqueta y nada más: sin "
            "justificación, sin matices, sin alternativas. Si el material no permite "
            "decidir, la etiqueta es \"indeterminado\". Devuelves únicamente JSON válido."
        ),
        "ayuda": "Tarea mecánica de una línea. Un modelo pequeño basta y va mucho "
                 "más rápido.",
    },
}


# ===========================================================================
# Variables de los prompts
# ===========================================================================

VARIABLES = {
    "entrada": "Lo que escribiste al lanzar el flujo",
    "anterior": "La salida completa del paso inmediatamente anterior",
    "paso:ID": "La salida de un paso concreto, por su identificador",
    "contexto": "Material de tu biblioteca sobre el tema (afirmaciones con su cita)",
    "titulo": "Título del libro, ejercicio o plan sobre el que corre el flujo",
    "critica": "Los problemas que señaló el revisor. Solo en pasos de corrección",
}

# Un libro entero no cabe en un modelo de 7B, pero su extracción sí. Estas
# variables son el libro troceado en piezas que un paso puede pedir por separado:
# el que deduce la notación no gana nada leyendo el índice, y metérselo le quita
# ventana y lo distrae.
VARIABLES_LIBRO = {
    "libro:titulo": "Título del libro que se está analizando",
    "libro:datos": "Cifras del libro: páginas, cuántas afirmaciones de cada tipo, "
                   "cuántos conceptos, capítulos, figuras y símbolos",
    "libro:indice": "Índice detectado, con capítulos, páginas y temas de cada uno",
    "libro:conceptos": "Conceptos del libro con cuántas veces aparece cada uno y "
                       "desde qué página",
    "libro:muestra": "Una muestra de afirmaciones de cada tipo, repartida por todo "
                     "el libro (no solo del principio, que siempre es más fácil)",
    "libro:simbolos": "La notación que usa el libro, con su significado",
    "libro:figuras": "Figuras y tablas con su pie y su página",
    "libro:preguntas": "Preguntas que el propio texto permite responder",
    "libro:relaciones": "Qué concepto del libro depende de cuál",
}

_PATRON_VAR = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?::[a-zA-Z0-9_\-]+)?)\}")


def variables_usadas(prompt: str) -> List[str]:
    return sorted(set(_PATRON_VAR.findall(prompt or "")))


# ===========================================================================
# Validación de un flujo
# ===========================================================================

def validar_flujo(flujo: Dict[str, Any]) -> List[str]:
    """ Problemas de un flujo, en lenguaje de quien lo está montando.

    Se valida antes de ejecutar porque un flujo de cinco pasos tarda minutos: que
    falle en el paso cuatro por una variable mal escrita es tiempo tirado.
    """
    problemas: List[str] = []
    pasos = flujo.get("pasos") or []

    if not pasos:
        return ["El flujo no tiene ningún paso"]
    if len(pasos) > MAX_PASOS:
        problemas.append(f"Demasiados pasos ({len(pasos)}); el máximo es {MAX_PASOS}")
    if not (flujo.get("nombre") or "").strip():
        problemas.append("El flujo necesita un nombre")

    ids: List[str] = []
    for n, paso in enumerate(pasos, 1):
        etiqueta = f"Paso {n} ({paso.get('nombre') or 'sin nombre'})"
        pid = (paso.get("id") or "").strip()
        if not pid:
            problemas.append(f"{etiqueta}: le falta el identificador")
        elif pid in ids:
            problemas.append(f"{etiqueta}: el identificador '{pid}' está repetido")
        ids.append(pid)

        if not (paso.get("prompt") or "").strip():
            problemas.append(f"{etiqueta}: no tiene instrucción")
        if paso.get("rol") not in ROLES:
            problemas.append(f"{etiqueta}: rol desconocido '{paso.get('rol')}'")
        if not (paso.get("modelo") or "").strip():
            problemas.append(f"{etiqueta}: no tiene modelo asignado")

        for var in variables_usadas(paso.get("prompt", "")):
            if var.startswith("paso:"):
                objetivo = var.split(":", 1)[1]
                if objetivo not in ids[:-1]:
                    problemas.append(
                        f"{etiqueta}: usa {{{var}}}, pero no hay ningún paso anterior "
                        f"con ese identificador")
            elif var not in VARIABLES and var not in VARIABLES_LIBRO and var != "critica":
                problemas.append(f"{etiqueta}: la variable {{{var}}} no existe")

        if n == 1 and "anterior" in variables_usadas(paso.get("prompt", "")):
            problemas.append(f"{etiqueta}: usa {{anterior}}, pero es el primer paso")

        if "critica" in variables_usadas(paso.get("prompt", "")):
            # {critica} solo tiene contenido si un revisor devolvió el trabajo a
            # ESTE paso. En cualquier otro sitio llega vacía y deja el prompt
            # diciendo "Problemas detectados:" seguido de nada.
            lo_revisan = any((otro.get("si_falla") or {}).get("volver_a") == pid
                             for otro in pasos)
            if not lo_revisan:
                problemas.append(
                    f"{etiqueta}: usa {{critica}}, pero ningún revisor le devuelve el "
                    f"trabajo, así que llegaría siempre vacía. Usa {{paso:id}} del "
                    f"revisor si lo que quieres es leer su informe")

        vuelta = paso.get("si_falla") or {}
        if vuelta:
            destino = vuelta.get("volver_a")
            if destino not in ids[:-1]:
                problemas.append(
                    f"{etiqueta}: al fallar vuelve a '{destino}', que no es un paso "
                    f"anterior")
            if paso.get("rol") not in ("criticar", "verificar"):
                problemas.append(
                    f"{etiqueta}: solo un revisor o un verificador puede devolver el "
                    f"trabajo a un paso anterior")
    return problemas


def plan_de_modelos(flujo: Dict[str, Any]) -> Dict[str, Any]:
    """ Cuántas veces habrá que cargar un modelo, y qué cuesta eso.

    Con 6 GB de VRAM solo cabe un modelo a la vez, así que alternar entre dos en
    pasos consecutivos significa recargarlos desde disco. Un flujo A-B-A-B paga
    cuatro cargas; el mismo flujo reordenado a A-A-B-B paga dos. Conviene saberlo
    antes, no después.
    """
    pasos = flujo.get("pasos") or []
    secuencia = [p.get("modelo") for p in pasos if p.get("modelo")]
    cargas = 0
    ultimo = None
    for m in secuencia:
        if m != ultimo:
            cargas += 1
            ultimo = m
    distintos = sorted(set(secuencia))
    minimo = len(distintos)

    vram = max((MODELOS.get(m, {}).get("vram_gb", 0) for m in distintos), default=0)
    return {
        "modelos": distintos,
        "cargas": cargas,
        "cargas_minimas": minimo,
        "recargas_evitables": max(0, cargas - minimo),
        "vram_mayor_gb": vram,
        "cabe_en_vram": vram <= VRAM_TIPICA_GB - 0.6 if vram else True,
        "segundos_estimados_de_carga": cargas * 8,
    }


# ===========================================================================
# Ejecución
# ===========================================================================

CARACTERES_POR_TOKEN = 3.6


def _recortar(texto: str, tope_tokens: int, etiqueta: str = "") -> str:
    """ Recorta por el medio, conservando principio y final.

    Truncar por el final es lo peor que se puede hacer con la salida de un agente:
    las conclusiones están al final. Se quedan las dos puntas y se dice en medio
    que falta algo, para que el modelo no crea que el texto acaba ahí.
    """
    tope = int(tope_tokens * CARACTERES_POR_TOKEN)
    if len(texto) <= tope:
        return texto
    mitad = tope // 2 - 60
    aviso = f"\n\n[… recortado{' de ' + etiqueta if etiqueta else ''}, "
    aviso += f"{len(texto) - tope} caracteres omitidos …]\n\n"
    return texto[:mitad] + aviso + texto[-mitad:]


class FlowEngine:
    """ Ejecuta un flujo paso a paso, emitiendo lo que va pasando.

    Devuelve un generador en lugar de un resultado: un flujo de cinco pasos con
    modelos locales tarda minutos, y mirar una pantalla congelada durante ese rato
    no dice si va bien, si se atascó o si el modelo se está cargando.
    """

    def __init__(self, ai_engine, context_assembler=None, num_ctx: int = 4096,
                 gobernador=None):
        self.ai = ai_engine
        self.contexto = context_assembler
        self.num_ctx = num_ctx
        # Gobernador térmico (recursos.termico.Gobernador). Lo pone la aplicación:
        # un flujo de muchos pasos es carga sostenida y en un portátil la GPU se
        # calienta. Pausa entre pasos y también a mitad de una generación. Sin él
        # (pruebas con motores falsos), no se pausa nunca.
        self.gobernador = gobernador
        self._avisar = lambda evento: None
        self._stop_event = threading.Event()

    def detener(self) -> None:
        """ Detiene la ejecución del flujo de agentes en curso """
        self._stop_event.set()

    # -- construcción del prompt -------------------------------------------

    def _valores(self, flujo, paso, entrada, salidas, orden, critica) -> Dict[str, str]:
        anterior = salidas.get(orden[-1], "") if orden else ""
        valores = {
            "entrada": entrada,
            "anterior": anterior,
            "titulo": flujo.get("titulo") or flujo.get("nombre") or "",
            "critica": critica or "",
            "contexto": "",
        }
        for pid, salida in salidas.items():
            valores[f"paso:{pid}"] = salida
        return valores

    def _contexto_biblioteca(self, consulta: str, presupuesto: int) -> str:
        if not self.contexto or not consulta.strip():
            return ""
        try:
            ctx = self.contexto.ensamblar(consulta, presupuesto_tokens=presupuesto)
            return "" if ctx.get("vacio") else ctx["texto"]
        except Exception:
            return ""

    def _render(self, plantilla: str, valores: Dict[str, str], presupuesto: int) -> str:
        """ Sustituye las variables repartiendo el presupuesto entre las que se usan.

        Si un paso mete tres salidas anteriores en su prompt y cada una ocupa media
        ventana, el modelo recibe un prompt truncado por Ollama sin avisar y responde
        a medias. Repartir aquí es lo que evita eso.
        """
        usadas = [v for v in variables_usadas(plantilla) if valores.get(v)]
        if not usadas:
            return plantilla
        # La plantilla misma consume; el resto se reparte entre las variables
        libre = max(200, presupuesto - int(len(plantilla) / CARACTERES_POR_TOKEN))
        por_variable = max(150, libre // len(usadas))

        def reemplazo(m):
            nombre = m.group(1)
            if nombre not in valores:
                return m.group(0)
            return _recortar(valores[nombre], por_variable, nombre)

        return _PATRON_VAR.sub(reemplazo, plantilla)

    # -- llamada al modelo -------------------------------------------------

    # Roles en los que pensar en voz alta ESTORBA: la salida tiene que ser JSON o
    # texto limpio, y el bloque de razonamiento lo ensucia y gasta ventana. En los
    # demás, pensar es exactamente lo que aporta el paso.
    ROLES_SIN_PENSAR = {"extraer", "clasificar", "programar", "corregir"}

    @classmethod
    def debe_pensar(cls, paso: Dict[str, Any]) -> Optional[bool]:
        """ Si este paso quiere razonamiento en voz alta, cuando el modelo lo permita.

        Devuelve None para los modelos que no lo traen: mandarles el campo no les
        afecta, pero preguntar por él deja claro en el registro qué se pidió.
        """
        modelo = paso.get("modelo") or ""
        info = MODELOS.get(modelo) or {}
        if info.get("piensa") != "conmutable":
            return None
        if paso.get("pensar") is not None:          # decisión explícita del usuario
            return bool(paso["pensar"])
        return paso.get("rol") not in cls.ROLES_SIN_PENSAR

    def _llamar(self, paso: Dict[str, Any], prompt: str) -> str:
        rol = ROLES.get(paso.get("rol"), ROLES["razonar"])
        sistema = (paso.get("sistema") or "").strip() or rol["sistema"]
        pensar = self.debe_pensar(paso)
        kwargs = {
            "model": paso.get("modelo"),
            "system_prompt": sistema,
            "options": {"temperature": float(paso.get("temperatura", rol["temperatura"])),
                        "num_predict": int(paso.get("max_tokens", 1200))},
        }
        # Solo se manda `think` cuando el modelo lo tiene conmutable. Enviarlo
        # siempre obligaría a todo motor de inferencia a aceptar el parámetro, y no
        # significa nada para los que no piensan en voz alta.
        if pensar is not None:
            kwargs["think"] = pensar
        # Las capas de configuración del uso "flujos" (solo el motor real lo admite)
        if getattr(self.ai, "admite_uso", False) is True:
            kwargs["uso"] = "flujos"
        if self.gobernador is not None and hasattr(self.ai, "generar_con_pausas"):
            # Con gobernador térmico: la generación puede parar a enfriar la GPU a
            # mitad y retomarse después sin perder lo ya escrito
            salida = self.ai.generar_con_pausas(
                prompt, gobernador=self.gobernador, cancelar=self._stop_event,
                avisar=self._avisar, **kwargs).strip()
            return _sin_pensamiento(salida)
        partes = []
        for trozo in self.ai.generate_response(prompt, **kwargs):
            partes.append(trozo)
        salida = "".join(partes).strip()
        # Algunos modelos devuelven el razonamiento dentro del texto en vez de en
        # su campo aparte. Si el paso pedía JSON, hay que quitarlo o no parseará.
        return _sin_pensamiento(salida)

    def _con_formato(self, paso, prompt) -> tuple:
        """ Ejecuta el paso y, si pedía JSON y no lo devolvió, lo reintenta una vez.

        El reintento señala el fallo concreto en lugar de repetir la misma petición:
        un modelo que ya se equivocó con el mismo prompt tiende a equivocarse igual.
        """
        rol = ROLES.get(paso.get("rol"), ROLES["razonar"])
        formato = paso.get("formato") or rol["formato"]
        salida = self._llamar(paso, prompt)
        if formato != "json":
            return salida, None

        datos = _json_de(salida)
        if datos is not None:
            return json.dumps(datos, ensure_ascii=False, indent=1), datos

        reintento = (prompt + "\n\n---\nTu respuesta anterior no era JSON válido. "
                     "Devuelve EXCLUSIVAMENTE el objeto JSON, sin texto alrededor, "
                     "sin ``` y sin explicaciones.")
        salida = self._llamar(paso, reintento)
        datos = _json_de(salida)
        if datos is None:
            return salida, None
        return json.dumps(datos, ensure_ascii=False, indent=1), datos

    def _paso_con_avisos(self, paso, prompt) -> Generator[Dict[str, Any], None, None]:
        cola: "queue.Queue" = queue.Queue()
        resultado: Dict[str, Any] = {}

        def trabajar():
            try:
                resultado["salida"], resultado["datos"] = self._con_formato(paso, prompt)
            except Exception as err:          # se relanza en el hilo del flujo
                resultado["error"] = err
            finally:
                cola.put(None)

        self._avisar = cola.put
        hilo = threading.Thread(target=trabajar, daemon=True, name="prig-paso-flujo")
        hilo.start()
        try:
            while True:
                evento = cola.get()
                if evento is None:
                    break
                yield evento
        finally:
            self._avisar = lambda evento: None
            hilo.join(timeout=1)
        if "error" in resultado:
            raise resultado["error"]
        yield {"tipo": "_resultado", "salida": resultado["salida"], "datos": resultado["datos"]}

    # -- el bucle ----------------------------------------------------------

    def ejecutar(self, flujo: Dict[str, Any], entrada: str = "",
                 consulta_contexto: str = "",
                 extra: Optional[Dict[str, str]] = None
                 ) -> Generator[Dict[str, Any], None, None]:
        self._stop_event.clear()
        problemas = validar_flujo(flujo)
        if problemas:
            yield {"tipo": "error", "mensaje": "El flujo tiene problemas",
                   "problemas": problemas}
            return

        pasos = flujo["pasos"]
        por_id = {p["id"]: p for p in pasos}
        plan = plan_de_modelos(flujo)
        yield {"tipo": "inicio", "pasos": len(pasos), "plan": plan,
               "comenzado": datetime.now().isoformat()}

        salidas: Dict[str, str] = {}
        datos_json: Dict[str, Any] = {}
        orden: List[str] = []
        registro: List[Dict[str, Any]] = []
        critica_pendiente = ""
        vueltas = 0
        indice = 0
        modelo_cargado = None
        t_inicio = time.time()

        while indice < len(pasos):
            if self._stop_event.is_set():
                yield {"tipo": "cancelado", "mensaje": "Flujo de análisis detenido."}
                return
            paso = pasos[indice]
            pid = paso["id"]
            rol = ROLES.get(paso.get("rol"), ROLES["razonar"])

            presupuesto = max(400, int(self.num_ctx * 0.6))
            valores = self._valores(flujo, paso, entrada, salidas, orden, critica_pendiente)
            valores.update(extra or {})
            if "contexto" in variables_usadas(paso.get("prompt", "")):
                consulta = consulta_contexto or entrada
                valores["contexto"] = self._contexto_biblioteca(consulta, presupuesto // 2)

            prompt = self._render(paso["prompt"], valores, presupuesto)

            # Si venimos de una vuelta atrás, el paso TIENE que ver la crítica. Sin
            # esto se reejecuta con el prompt idéntico y el modelo devuelve lo mismo:
            # el bucle daría vueltas sin arreglar nada. Solo se añade si el prompt no
            # la pedía ya por su cuenta con {critica}.
            if critica_pendiente and "critica" not in variables_usadas(paso["prompt"]):
                prompt += ("\n\n---\nTu intento anterior fue revisado y tiene estos "
                           "problemas. Rehaz el trabajo corrigiéndolos; lo que no esté "
                           "señalado aquí ya estaba bien y no hace falta cambiarlo.\n\n"
                           + _recortar(critica_pendiente, presupuesto // 4, "la revisión"))

            if self.gobernador is not None:
                avisos: List[Dict[str, Any]] = []
                pausa = self.gobernador.antes_de_trabajar(self._stop_event, avisos.append)
                for aviso in avisos:
                    yield {**aviso, "indice": indice, "id": pid}
                if pausa and self._stop_event.is_set():
                    continue

            recarga = paso.get("modelo") != modelo_cargado
            yield {"tipo": "paso_inicio", "indice": indice, "id": pid,
                   "nombre": paso.get("nombre") or pid, "rol": paso.get("rol"),
                   "modelo": paso.get("modelo"), "recarga_modelo": recarga,
                   "tokens_prompt": int(len(prompt) / CARACTERES_POR_TOKEN)}
            modelo_cargado = paso.get("modelo")

            t0 = time.time()
            try:
                if self.gobernador is not None:
                    # En un hilo, para poder emitir las pausas térmicas EN VIVO
                    # mientras el paso está en marcha
                    salida, datos = None, None
                    for evento in self._paso_con_avisos(paso, prompt):
                        if evento.get("tipo") == "_resultado":
                            salida, datos = evento["salida"], evento["datos"]
                        else:
                            yield {**evento, "indice": indice, "id": pid}
                else:
                    salida, datos = self._con_formato(paso, prompt)
            except Exception as err:
                yield {"tipo": "paso_error", "indice": indice, "id": pid,
                       "mensaje": str(err)}
                salida, datos = f"[el paso falló: {err}]", None
            dt = time.time() - t0

            salidas[pid] = salida
            if datos is not None:
                datos_json[pid] = datos
            if pid not in orden:
                orden.append(pid)
            else:
                orden.append(pid)      # una repetición cuenta como paso posterior

            registro.append({
                "id": pid, "nombre": paso.get("nombre") or pid, "rol": paso.get("rol"),
                "modelo": paso.get("modelo"), "segundos": round(dt, 1),
                "prompt": prompt, "salida": salida, "vuelta": vueltas,
            })

            yield {"tipo": "paso_fin", "indice": indice, "id": pid,
                   "nombre": paso.get("nombre") or pid, "salida": salida,
                   "datos": datos, "segundos": round(dt, 1),
                   "formato": paso.get("formato") or rol["formato"]}

            # ¿el revisor devuelve el trabajo?
            volver = self._debe_volver(paso, datos)
            if volver and vueltas < MAX_VUELTAS_TOTALES:
                destino = paso["si_falla"]["volver_a"]
                tope = int((paso.get("si_falla") or {}).get("max_vueltas", 2))
                hechas = sum(1 for r in registro if r["id"] == destino) - 1
                if hechas < tope:
                    vueltas += 1
                    critica_pendiente = _texto_critica(datos)
                    yield {"tipo": "vuelta", "desde": pid, "hacia": destino,
                           "vuelta": hechas + 1, "de": tope,
                           "motivo": critica_pendiente[:400]}
                    indice = next(i for i, p in enumerate(pasos) if p["id"] == destino)
                    continue
                yield {"tipo": "aviso", "mensaje":
                       f"'{paso.get('nombre') or pid}' sigue sin aprobar tras {tope} "
                       f"vueltas; se continúa con lo que hay"}
            critica_pendiente = ""
            indice += 1

        final = salidas.get(orden[-1], "") if orden else ""
        yield {"tipo": "fin", "final": final, "salidas": salidas, "datos": datos_json,
               "registro": registro, "segundos": round(time.time() - t_inicio, 1),
               "modelos": sorted({p.get("modelo") for p in pasos if p.get("modelo")})}

    @staticmethod
    def _debe_volver(paso: Dict[str, Any], datos: Any) -> bool:
        if not (paso.get("si_falla") or {}).get("volver_a"):
            return False
        if not isinstance(datos, dict):
            return False
        if datos.get("aprobado") is False:
            return True
        return bool(datos.get("problemas") or datos.get("incorrectas"))


_PENSAMIENTO = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>\s*", re.S | re.I)


def _sin_pensamiento(texto: str) -> str:
    """ Quita el bloque de razonamiento que algunos modelos dejan en el texto.

    Se hace aunque se haya pedido apagarlo: un modelo que ignora la petición no
    debe romper el paso siguiente, y un <think> sin cerrar delante de un JSON hace
    que no parsee.
    """
    limpio = _PENSAMIENTO.sub("", texto or "")
    # Bloque abierto y sin cerrar: se descarta todo hasta donde llegue
    if "<think" in limpio.lower() and "</think" not in limpio.lower():
        corte = limpio.lower().find("<think")
        limpio = limpio[:corte]
    return limpio.strip()


def _json_de(texto: str) -> Optional[Any]:
    """ Primer objeto o lista JSON del texto, tolerando markdown alrededor """
    if not texto:
        return None
    for abre, cierra in (("{", "}"), ("[", "]")):
        inicio = texto.find(abre)
        if inicio < 0:
            continue
        profundidad, en_cadena, escape = 0, False, False
        for i in range(inicio, len(texto)):
            c = texto[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                en_cadena = not en_cadena
                continue
            if en_cadena:
                continue
            if c == abre:
                profundidad += 1
            elif c == cierra:
                profundidad -= 1
                if profundidad == 0:
                    try:
                        return json.loads(texto[inicio:i + 1])
                    except Exception:
                        break
    return None


def _texto_critica(datos: Any) -> str:
    """ Los problemas del revisor, en la forma en que el corrector puede usarlos """
    if not isinstance(datos, dict):
        return str(datos)[:1500]
    lineas = []
    for p in (datos.get("problemas") or []):
        if isinstance(p, dict):
            lineas.append(f"- En {p.get('donde', 'el texto')}: {p.get('que', '')}. "
                          f"Arreglo sugerido: {p.get('arreglo', '—')}")
        else:
            lineas.append(f"- {p}")
    for p in (datos.get("incorrectas") or []):
        if isinstance(p, dict):
            lineas.append(f"- «{p.get('afirmacion', '')}» es incorrecta: {p.get('fallo', '')}")
        else:
            lineas.append(f"- {p}")
    return "\n".join(lineas) or json.dumps(datos, ensure_ascii=False)[:1500]


# ===========================================================================
# Persistencia
# ===========================================================================

class FlowStore:
    """ Flujos e historial de ejecuciones, en el workspace.

    El historial guarda el prompt exacto que recibió cada agente. Ocupa, pero es
    lo único que permite arreglar un flujo que da malos resultados: sin ver qué
    leyó cada paso, ajustar los prompts es adivinar.
    """

    def __init__(self, workspace_dir: Optional[str] = None):
        base = os.path.abspath(workspace_dir or os.getcwd())
        self.data_dir = os.path.join(base, ".prig_dataset")
        os.makedirs(self.data_dir, exist_ok=True)
        self.ruta = os.path.join(self.data_dir, "flujos.json")
        self.ruta_historial = os.path.join(self.data_dir, "flujos_historial.json")
        self._lock = threading.Lock()
        self._flujos: Dict[str, Dict[str, Any]] = {}
        self._historial: List[Dict[str, Any]] = []
        self._cargar()

    def _cargar(self):
        for ruta, destino in ((self.ruta, "_flujos"), (self.ruta_historial, "_historial")):
            if not os.path.isfile(ruta):
                continue
            try:
                with open(ruta, encoding="utf-8") as f:
                    setattr(self, destino, json.load(f))
            except Exception as err:
                print(f"⚠️ No se pudo leer {os.path.basename(ruta)} ({err}); se empieza vacío.")

    def _guardar(self, ruta: str, datos: Any):
        # Escritura atómica: un corte a media escritura no debe dejar el archivo
        # a medias, que es como se pierden todos los flujos de golpe.
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta)

    # -- flujos ------------------------------------------------------------

    def listar(self) -> List[Dict[str, Any]]:
        return sorted(self._flujos.values(),
                      key=lambda f: f.get("actualizado", ""), reverse=True)

    def obtener(self, flujo_id: str) -> Optional[Dict[str, Any]]:
        return self._flujos.get(flujo_id)

    def guardar(self, flujo: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            fid = flujo.get("id") or f"flujo_{int(time.time() * 1000):x}"
            flujo["id"] = fid
            flujo.setdefault("creado", datetime.now().isoformat())
            flujo["actualizado"] = datetime.now().isoformat()
            self._flujos[fid] = flujo
            if len(self._flujos) > MAX_FLUJOS:
                sobra = sorted(self._flujos.values(),
                               key=lambda f: f.get("actualizado", ""))[0]
                self._flujos.pop(sobra["id"], None)
            self._guardar(self.ruta, self._flujos)
        return flujo

    def borrar(self, flujo_id: str) -> bool:
        with self._lock:
            if flujo_id not in self._flujos:
                return False
            self._flujos.pop(flujo_id)
            self._guardar(self.ruta, self._flujos)
        return True

    # -- historial ---------------------------------------------------------

    def anotar_ejecucion(self, flujo: Dict[str, Any], entrada: str,
                         registro: List[Dict[str, Any]], segundos: float) -> str:
        with self._lock:
            eid = f"eje_{int(time.time() * 1000):x}"
            self._historial.insert(0, {
                "id": eid, "flujo_id": flujo.get("id"),
                "flujo_nombre": flujo.get("nombre"),
                "cuando": datetime.now().isoformat(),
                "entrada": entrada[:2000], "segundos": segundos,
                "pasos": registro,
            })
            del self._historial[MAX_HISTORIAL:]
            self._guardar(self.ruta_historial, self._historial)
        return eid

    def historial(self, flujo_id: Optional[str] = None,
                  limite: int = 20) -> List[Dict[str, Any]]:
        filas = [h for h in self._historial
                 if not flujo_id or h.get("flujo_id") == flujo_id]
        # El resumen no lleva los prompts: son enormes y solo hacen falta al abrir
        # una ejecución concreta.
        return [{k: v for k, v in h.items() if k != "pasos"} |
                {"n_pasos": len(h.get("pasos", []))} for h in filas[:limite]]

    def ejecucion(self, eid: str) -> Optional[Dict[str, Any]]:
        return next((h for h in self._historial if h["id"] == eid), None)


# ===========================================================================
# Plantillas
# ===========================================================================

def _paso(pid, nombre, rol, modelo, prompt, **extra):
    base = {"id": pid, "nombre": nombre, "rol": rol, "modelo": modelo,
            "prompt": prompt, "sistema": "", "max_tokens": 1200}
    base["temperatura"] = extra.pop("temperatura", ROLES[rol]["temperatura"])
    base["formato"] = extra.pop("formato", ROLES[rol]["formato"])
    base.update(extra)
    return base


def plantillas(modelo_base: str = "qwen2.5-coder:7b",
               modelo_razona: str = "") -> List[Dict[str, Any]]:
    """ Flujos listos para usar, como punto de partida.

    `modelo_razona` es el que se pone en los pasos de análisis y crítica. Si no
    tienes ninguno de razonamiento descargado se usa el mismo de base: el flujo
    funciona igual, solo rinde menos en esos pasos.
    """
    razona = modelo_razona or modelo_base

    return [
        {
            "id": "plantilla_ficha_libro",
            "nombre": "Ficha completa de un libro",
            "descripcion": "Analiza un libro entero y saca todo lo que hace falta para "
                           "planificar: qué enseña, qué da por sabido, cómo leerlo, "
                           "dónde practicar y qué NO cubre. Siete pasos.",
            "ambito": "ficha",
            # Los pasos van agrupados por modelo a propósito: los tres de extracción
            # primero y los de razonamiento después. Con 6 GB de VRAM solo cabe un
            # modelo a la vez, así que alternarlos costaría una recarga por paso.
            "pasos": [
                _paso("temario", "Mapear el temario", "extraer", modelo_base,
                      "Libro: {libro:titulo}\n{libro:datos}\n\n"
                      "Índice detectado:\n{libro:indice}\n\n"
                      "Conceptos con su frecuencia y primera aparición:\n{libro:conceptos}\n\n"
                      "Construye el mapa del temario. Para cada capítulo: qué conceptos "
                      "se tratan ahí (usa los de la lista, no inventes), en qué páginas, "
                      "qué dificultad tiene del 1 al 5, y de qué capítulos anteriores "
                      "depende.\n"
                      "Si el índice no trae páginas, dedúcelas de la primera aparición "
                      "de los conceptos y márcalo como aproximado.\n\n"
                      'JSON: {{"capitulos": [{{"capitulo": "3", "titulo": "...", '
                      '"paginas": "112-150", "paginas_aproximadas": false, '
                      '"conceptos": ["..."], "dificultad": 3, "depende_de": ["1", "2"], '
                      '"vale_la_pena_si": "quieres entender ..."}}]}}',
                      max_tokens=1800),

                _paso("notacion", "Recoger la notación", "extraer", modelo_base,
                      "Libro: {libro:titulo} (campo: se indica abajo)\n{libro:datos}\n\n"
                      "Símbolos detectados:\n{libro:simbolos}\n\n"
                      "Muestra de afirmaciones:\n{libro:muestra}\n\n"
                      "Reúne la notación de este libro. Para cada símbolo: qué significa "
                      "AQUÍ, y si sabes que otros libros del mismo campo usan ese símbolo "
                      "para otra cosa, dilo — confundir notación entre libros es de los "
                      "errores que más tiempo hacen perder.\n"
                      "No inventes símbolos que no aparezcan en la lista.\n\n"
                      'JSON: {{"simbolos": [{{"simbolo": "∇", "significa": "...", '
                      '"pagina": 112, "cuidado": "" }}], '
                      '"convenciones": ["escribe los vectores en negrita", "..."]}}'),

                _paso("prerrequisitos", "Deducir qué da por sabido", "extraer", modelo_base,
                      "Libro: {libro:titulo}\n{libro:datos}\n\n"
                      "Índice:\n{libro:indice}\n\n"
                      "Conceptos que usa:\n{libro:conceptos}\n\n"
                      "Dependencias entre conceptos:\n{libro:relaciones}\n\n"
                      "Deduce qué da por sabido el libro: aquello que USA pero no "
                      "explica. Se nota en los conceptos que aparecen desde las primeras "
                      "páginas sin que ningún capítulo los introduzca, y en las "
                      "dependencias que apuntan a algo que el libro nunca define.\n\n"
                      'JSON: {{"asume": [{{"tema": "cálculo de una variable", '
                      '"como_de_necesario": "imprescindible|conviene|se puede ir mirando", '
                      '"se_ve_en": "lo usa desde el capítulo 2 sin explicarlo"}}], '
                      '"nivel_de_entrada": "qué hay que traer para no perderse"}}'),

                _paso("identidad", "Qué enseña de verdad", "razonar", razona,
                      "Libro: {libro:titulo}\n{libro:datos}\n\n"
                      "Temario reconstruido:\n{paso:temario}\n\n"
                      "Da por sabido:\n{paso:prerrequisitos}\n\n"
                      "Muestra de cómo escribe:\n{libro:muestra}\n\n"
                      "Analiza qué enseña este libro DE VERDAD, más allá de su título. "
                      "Fíjate en el reparto de tipos de afirmación: un libro con muchas "
                      "fórmulas y pocos ejemplos es de referencia; uno con muchos "
                      "procedimientos y ejemplos es de aprender haciendo.\n"
                      "Propón además rutas de lectura: para un objetivo concreto, qué "
                      "capítulos leer, en qué orden, y cuáles se pueden saltar sin "
                      "perderse nada.\n\n"
                      'JSON: {{"que_cubre": "una frase honesta", '
                      '"nivel": "introductorio|intermedio|avanzado|referencia", '
                      '"para_quien": "...", "estilo": "...", '
                      '"hay_que_leerlo_entero": false, '
                      '"rutas": [{{"objetivo": "...", "capitulos": ["1","3","7"], '
                      '"saltar": ["2"], "horas_estimadas": 12}}]}}',
                      max_tokens=1600),

                _paso("ejercicios", "Material para ejercicios", "razonar", razona,
                      "Libro: {libro:titulo}\n\n"
                      "Temario:\n{paso:temario}\n\n"
                      "Muestra de afirmaciones por tipo:\n{libro:muestra}\n\n"
                      "Figuras:\n{libro:figuras}\n\n"
                      "Preguntas que el propio texto permite responder:\n{libro:preguntas}\n\n"
                      "Di sobre qué conceptos de este libro se puede montar un ejercicio "
                      "de verdad y de qué tipo. Un concepto del que solo hay una "
                      "definición NO sirve: hace falta un procedimiento, un ejemplo "
                      "resuelto o una fórmula, algo que el alumno pueda HACER.\n"
                      "Para cada uno, di qué error cometerá quien crea que lo entendió "
                      "y no — eso es lo que un buen ejercicio tiene que poner a prueba.\n\n"
                      'JSON: {{"propuestas": [{{"concepto": "...", '
                      '"tipo": "implementar|calcular|demostrar|depurar|comparar", '
                      '"apoyado_en": "p.228, ejemplo resuelto", '
                      '"error_que_destapa": "...", "dificultad": 3}}], '
                      '"conceptos_sin_material": ["los que solo tienen definición"]}}',
                      max_tokens=1600),

                _paso("lagunas", "Qué NO cubre", "razonar", razona,
                      "Libro: {libro:titulo}, del campo indicado en:\n{libro:datos}\n\n"
                      "Temario:\n{paso:temario}\n\nQué enseña:\n{paso:identidad}\n\n"
                      "Di qué temas importantes de este campo NO están en el libro, o "
                      "están solo de pasada. Es la parte que más se olvida y la más cara: "
                      "un plan de estudio que promete algo que el libro no trae manda al "
                      "alumno a buscar lo que no está.\n"
                      "Distingue lo que falta de verdad de lo que simplemente no es el "
                      "tema del libro.\n\n"
                      'JSON: {{"no_cubre": [{{"tema": "...", '
                      '"gravedad": "hace falta otro libro|se puede vivir sin ello", '
                      '"por_que_importa": "..."}}], '
                      '"tratado_de_pasada": ["..."]}}'),

                _paso("revisar", "Comprobar contra lo extraído", "criticar", razona,
                      "Lo que se ha deducido del libro:\n"
                      "Temario:\n{paso:temario}\n\nQué enseña:\n{paso:identidad}\n\n"
                      "Contra lo que de verdad se extrajo del texto:\n"
                      "{libro:datos}\n\nConceptos con su frecuencia:\n{libro:conceptos}\n\n"
                      "Busca dónde la ficha promete más de lo que el libro da: capítulos "
                      "descritos como profundos sobre conceptos que apenas aparecen, "
                      "temas del temario que no salen en la lista de conceptos, páginas "
                      "inventadas, o un nivel declarado que no encaja con el reparto de "
                      "tipos de afirmación.\n"
                      "Si la ficha es honesta, dilo y no busques peros.",
                      si_falla={"volver_a": "temario", "max_vueltas": 1}),
            ],
        },
        {
            "id": "plantilla_libro",
            "nombre": "Analizar un tema de la biblioteca",
            "descripcion": "Reúne lo que dicen tus libros, lo critica y redacta una "
                           "explicación verificada. Cuatro pasos, dos modelos.",
            "ambito": "libro",
            "pasos": [
                _paso("reunir", "Reunir material", "extraer", modelo_base,
                      "Tema a estudiar: {entrada}\n\n"
                      "Material de la biblioteca:\n{contexto}\n\n"
                      "Ordena lo que dice el material sobre el tema. Devuelve JSON con "
                      '{"definiciones": [{"texto": "...", "cita": "...", "libro": "...", '
                      '"pagina": N}], "formulas": [...], "prerrequisitos": ["..."], '
                      '"lagunas": ["lo que el material NO cubre del tema"]}.\n'
                      "Las citas se copian literalmente del material. Las lagunas son "
                      "importantes: di qué falta en lugar de rellenarlo."),
                _paso("analizar", "Analizar y conectar", "razonar", razona,
                      "Tema: {entrada}\n\nMaterial reunido:\n{paso:reunir}\n\n"
                      "Analiza: ¿en qué orden hay que entender estas ideas y por qué? "
                      "¿Qué concepto sostiene a cuál? ¿Dónde se suele atascar alguien "
                      "que aprende esto? Señala qué está respaldado por el material y "
                      "qué es inferencia tuya."),
                _paso("redactar", "Redactar la explicación", "redactar", modelo_base,
                      "Tema: {entrada}\n\nMaterial con sus citas:\n{paso:reunir}\n\n"
                      "Análisis:\n{paso:analizar}\n\n"
                      "Escribe la explicación para alguien que estudia esto por primera "
                      "vez. Cita libro y página cada vez que afirmes algo del material. "
                      "Si el análisis señaló lagunas, dilas al final en vez de taparlas.",
                      max_tokens=1800),
                _paso("revisar", "Revisar", "criticar", razona,
                      "Material original con sus citas:\n{paso:reunir}\n\n"
                      "Explicación a revisar:\n{paso:redactar}\n\n"
                      "Busca: afirmaciones que no estén respaldadas por el material, "
                      "citas atribuidas al libro equivocado, saltos donde se da por "
                      "sabido algo que no se explicó, y errores conceptuales.",
                      si_falla={"volver_a": "redactar", "max_vueltas": 2}),
            ],
            # No hay un paso de "corregir" al final a propósito: el revisor devuelve
            # el trabajo al redactor, que lo rehace viendo los problemas. Añadir
            # después un corrector sería un cuarto modelo cargándose para arreglar
            # algo que ya está arreglado.
        },
        {
            "id": "plantilla_ejercicio",
            "nombre": "Diseñar un ejercicio verificado",
            "descripcion": "Diseña el ejercicio, escribe la solución, la ejecuta "
                           "mentalmente y solo entonces redacta el enunciado.",
            "ambito": "ejercicio",
            "pasos": [
                _paso("disenar", "Diseñar", "razonar", razona,
                      "Tema: {entrada}\n\nMaterial de referencia:\n{contexto}\n\n"
                      "Diseña UN ejercicio de programación que obligue a entender el "
                      "tema, no a copiar un patrón. Explica qué concepto pone a prueba, "
                      "por qué no se puede resolver sin haberlo entendido, y cuál es el "
                      "error que cometerá quien crea que lo entendió y no."),
                _paso("resolver", "Escribir la solución", "programar", modelo_base,
                      "Diseño del ejercicio:\n{paso:disenar}\n\n"
                      "Escribe la solución de referencia en Python, completa y "
                      "ejecutable, y debajo los tests que debe pasar. Los tests tienen "
                      "que fallar con un esqueleto vacío y pasar con tu solución."),
                _paso("comprobar", "Comprobar la solución", "verificar", razona,
                      "Ejercicio:\n{paso:disenar}\n\nSolución y tests:\n{paso:resolver}\n\n"
                      "Recorre el código mentalmente con los casos de los tests y "
                      "comprueba que la solución los pasa de verdad. Revisa también "
                      "casos límite: vacío, negativo, un solo elemento, repetidos.",
                      si_falla={"volver_a": "resolver", "max_vueltas": 2}),
                _paso("enunciar", "Redactar el enunciado", "redactar", modelo_base,
                      "Diseño:\n{paso:disenar}\n\nSolución de referencia:\n{paso:resolver}\n\n"
                      "Escribe el enunciado para el alumno. Incluye el esqueleto de "
                      "partida y un ejemplo de entrada y salida. NO reveles la solución "
                      "ni la estrategia: el ejercicio pierde su valor."),
            ],
        },
        {
            "id": "plantilla_plan",
            "nombre": "Construir un plan de estudio",
            "descripcion": "Ordena los temas por dependencia, los reparte en sesiones "
                           "y comprueba que no haya saltos.",
            "ambito": "plan",
            "pasos": [
                _paso("temas", "Listar los temas", "extraer", modelo_base,
                      "Objetivo de aprendizaje: {entrada}\n\n"
                      "Material disponible en la biblioteca:\n{contexto}\n\n"
                      "Lista los temas que hay que dominar para llegar al objetivo. "
                      'Devuelve JSON: {"temas": [{"nombre": "...", "requiere": ["..."], '
                      '"en_biblioteca": true|false}]}. '
                      "Marca honestamente cuáles NO están cubiertos por el material."),
                _paso("ordenar", "Ordenar por dependencias", "razonar", razona,
                      "Objetivo: {entrada}\n\nTemas:\n{paso:temas}\n\n"
                      "Ordénalos de forma que ningún tema aparezca antes que aquello "
                      "que necesita. Agrúpalos en sesiones de unas dos horas. Para cada "
                      "sesión di qué se sabrá hacer al terminarla — no qué se habrá "
                      "leído."),
                _paso("huecos", "Buscar saltos", "criticar", razona,
                      "Temas y sus dependencias:\n{paso:temas}\n\n"
                      "Plan propuesto:\n{paso:ordenar}\n\n"
                      "Busca saltos: sesiones que usan algo que no se ha enseñado "
                      "todavía, sesiones demasiado cargadas para dos horas, y temas "
                      "marcados como fuera de la biblioteca que el plan da por "
                      "cubiertos.",
                      si_falla={"volver_a": "ordenar", "max_vueltas": 2}),
                _paso("final", "Redactar el plan", "redactar", modelo_base,
                      "Plan:\n{paso:ordenar}\n\nRevisión:\n{paso:huecos}\n\n"
                      "Escribe el plan definitivo sesión a sesión, con lo que se "
                      "practica en cada una y qué material de la biblioteca usar.",
                      max_tokens=1800),
            ],
        },
        {
            "id": "plantilla_dudas",
            "nombre": "Responder una duda con las fuentes",
            "descripcion": "Corto y barato: busca en la biblioteca, responde y "
                           "comprueba que lo dicho está respaldado. Tres pasos.",
            "ambito": "libro",
            "pasos": [
                _paso("buscar", "Buscar en la biblioteca", "extraer", modelo_base,
                      "Pregunta: {entrada}\n\nMaterial:\n{contexto}\n\n"
                      "Saca del material SOLO lo que responde a esa pregunta. "
                      'JSON: {"relevante": [{"dice": "...", "cita": "...", "libro": "...", '
                      '"pagina": N}], "responde_la_pregunta": true|false}.'),
                _paso("responder", "Responder", "redactar", modelo_base,
                      "Pregunta: {entrada}\n\nLo que dicen tus libros:\n{paso:buscar}\n\n"
                      "Responde apoyándote solo en eso, citando libro y página. Si el "
                      "material no responde la pregunta, dilo en la primera frase."),
                _paso("comprobar", "Comprobar el respaldo", "verificar", modelo_base,
                      "Material:\n{paso:buscar}\n\nRespuesta dada:\n{paso:responder}\n\n"
                      "Comprueba afirmación por afirmación si el material la respalda. "
                      "Señala las que no."),
            ],
        },
    ]
