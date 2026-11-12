---
name: ollama
description: "Guia oficial para gerenciamento, automação e inferência de modelos locais de linguagem via Ollama (CLI e biblioteca Python ollama), com suporte a saídas estruturadas (Structured Outputs via Pydantic / JSON Schema) e otimização para execução em notebooks com recursos moderados."
---

# Ollama — Guia de Automação e Inferência Local

Esta skill orienta o uso do **Ollama** para execução de modelos de linguagem (LLMs) diretamente no hardware local, sem custos de API externa e sem envio de dados para serviços em nuvem.

---

## 1. Comandos Essenciais do CLI

O Ollama é executado como serviço local em segundo plano (porta padrão `11434` no endereço `http://localhost:11434`).

| Comando | Descrição |
| :--- | :--- |
| `ollama list` | Lista todos os modelos baixados e seus tamanhos no disco. |
| `ollama ps` | Exibe os modelos atualmente carregados na memória RAM/VRAM. |
| `ollama pull <modelo>` | Baixa um novo modelo do registro oficial (ex: `ollama pull qwen2.5:3b`). |
| `ollama run <modelo>` | Inicia uma sessão de chat interativo no terminal. |
| `ollama show <modelo>` | Exibe detalhes técnicos do modelo (arquitetura, parâmetros, quantização, context window). |
| `ollama rm <modelo>` | Remove um modelo local para liberar espaço no disco. |
| `ollama stop <modelo>` | Descarrega o modelo da memória imediatamente. |

---

## 2. Modelos Recomendados para Execução em Notebook (CPU + Pouca VRAM)

Para máquinas com **16 GB de RAM**, GPU integrada/de entrada (**2 GB VRAM**) e espaço moderado em disco (40–50 GB livres):

| Modelo | Tamanho (Download / RAM) | Velocidade Típica | Recomendação / Uso |
| :--- | :---: | :---: | :--- |
| **`qwen2.5:3b`** | **~1.9 GB / ~2.5 GB RAM** | **25–40 tok/s** | **Padrão recomendado**: Extraordinária compreensão de português (PT-BR), jargões de negócios e aderência cirúrgica a Schemas JSON. |
| **`llama3.2:3b`** | **~2.0 GB / ~2.4 GB RAM** | **25–35 tok/s** | Redação natural de mensagens e conversação em inglês/português. |
| **`qwen2.5:7b`** | **~4.7 GB / ~5.8 GB RAM** | **8–14 tok/s** | Opção para tarefas que exigem raciocínio complexo ou redação mais elaborada. |

---

## 3. Integração com Python (`ollama`)

### 3.1. Instalação
```bash
pip install ollama
```

### 3.2. Cliente Síncrono e Assíncrono
```python
from ollama import Client, AsyncClient

# Cliente síncrono com host e timeout explícitos
client = Client(host="http://localhost:11434", timeout=60.0)

response = client.chat(
    model="qwen2.5:3b",
    messages=[{"role": "user", "content": "Explique o que é R&S em uma frase."}],
    options={"temperature": 0.2},
)
print(response.message.content)
```

---

## 4. Structured Outputs com Pydantic / JSON Schema

O Ollama oferece suporte nativo à geração de JSON estritamente em conformidade com esquemas Pydantic através do parâmetro `format`:

```python
from pydantic import BaseModel, Field
from ollama import Client

class AvaliacaoVaga(BaseModel):
    aderencia: str = Field(description="Nível: Alta, Média ou Baixa")
    pontos_fortes: list[str]
    pontos_atencao: list[str]
    score: float = Field(ge=0.0, le=100.0)

client = Client(host="http://localhost:11434")

# Passando o schema gerado pelo Pydantic:
response = client.chat(
    model="qwen2.5:3b",
    messages=[
        {"role": "system", "content": "Você é um especialista em recrutamento. Responda estritamente em JSON."},
        {"role": "user", "content": "Avalie a vaga de Analista Administrativo..."},
    ],
    format=AvaliacaoVaga.model_json_schema(),
    options={"temperature": 0.0},  # Deterministico
)

# Validação e desserialização tipada direta
resultado = AvaliacaoVaga.model_validate_json(response.message.content)
```

---

## 5. Boas Práticas e Resiliência em Notebooks

1. **Definir `temperature: 0.0`**: Essencial para saídas estruturadas confiáveis e sem alucinações.
2. **Definir `num_ctx` controlado**: Se os textos forem descrições de vagas ou mensagens de até 2.000 tokens, limite o `num_ctx` (ex: `options={"num_ctx": 4096}`) para poupar memória RAM.
3. **Health Check e Tratamento de Exceções**:
   Sempre encapsular chamadas de rede em `try/except` tratando `ConnectError` e `ResponseError`, acionando o fallback local caso o serviço Ollama não esteja rodando:
   ```python
   import httpx

   def check_ollama_online(base_url: str = "http://localhost:11434") -> bool:
       try:
           r = httpx.get(f"{base_url}/api/tags", timeout=2.0)
           return r.status_code == 200
       except Exception:
           return False
   ```
4. **Defesa contra Prompt Injection**: Textos de páginas externas (como vagas e perfis raspados) devem sempre ser delimitados como dados passivos no prompt (`<JOB_DESCRIPTION> ... </JOB_DESCRIPTION>`) instruindo o modelo a ignorar instruções contidas no conteúdo.
