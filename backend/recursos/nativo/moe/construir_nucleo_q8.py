"""Núcleo Q8 con el vocabulario recortado (lo que carga el motor MoE con «núcleo: q8»).

Toma del Q4 recortado los metadatos, el vocabulario, token_embd, output, la capa MTP y los
EXPERTOS, y del Q8_0 de unsloth el núcleo: atención, SSM, router y experto compartido (1,3 → 2,0 GB).
Medido contra una referencia Q8: la divergencia KL del Q4 baja de 0,071 a 0,022 (docs/motor-moe.md).

    python3 construir_nucleo_q8.py Q4_RECORTADO Q8_0 SALIDA
"""
import sys

import os
sys.path.insert(0, os.path.join(os.environ.get("PRIG_MOE_TRABAJO", os.path.expanduser("~/.cache/prig-moe")), "fork", "gguf-py"))
import gguf  # noqa: E402

DEL_VOCABULARIO = {"token_embd.weight", "output.weight"}


def main():
    q4 = gguf.GGUFReader(sys.argv[1])
    q8 = gguf.GGUFReader(sys.argv[2])
    salida = sys.argv[3]
    arch = q4.fields[gguf.Keys.General.ARCHITECTURE].contents()
    w = gguf.GGUFWriter(salida, arch)
    n_vocab = len(q4.fields["tokenizer.ggml.tokens"].data)
    for campo in q4.fields.values():
        if campo.name == gguf.Keys.General.ARCHITECTURE or campo.name.startswith("GGUF."):
            continue
        tipo = campo.types[0]
        sub = campo.types[-1] if tipo == gguf.GGUFValueType.ARRAY else None
        valor = campo.contents()
        if campo.name == "tokenizer.ggml.bos_token_id" and valor >= n_vocab:
            # El recorte del vocabulario dejó el BOS en 248044, fuera de rango: llama.cpp lo cambiaba
            # por el id 11 (un token normal). Es <|endoftext|>, igual que el EOS.
            valor = q4.fields["tokenizer.ggml.eos_token_id"].contents()
        w.add_key_value(campo.name, valor, tipo, sub_type=sub)

    de_q8 = {t.name: t for t in q8.tensors}
    elegidos, cambiados = [], 0
    for t in q4.tensors:
        otro = de_q8.get(t.name)
        if t.name not in DEL_VOCABULARIO and "_exps" not in t.name and otro is not None and list(otro.shape) == list(t.shape):
            elegidos.append(otro)
            cambiados += 1
        else:
            elegidos.append(t)
    for t in elegidos:
        w.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_ti_data_to_file()
    for t in elegidos:
        w.write_tensor_data(t.data)
    w.close()
    print(f"{cambiados} de {len(q4.tensors)} tensores del Q8_0; el resto (vocabulario, expertos, MTP) del Q4 recortado")


if __name__ == "__main__":
    main()
