---
license: mit
language:
- ja
- ko
pipeline_tag: translation
inference: false
---

# Japanese to Korean translator

Japanese to Korean translator model based on [EncoderDecoderModel](https://huggingface.co/docs/transformers/model_doc/encoder-decoder)([bert-japanese](https://huggingface.co/cl-tohoku/bert-base-japanese)+[kogpt2](https://github.com/SKT-AI/KoGPT2))

# Usage
## Demo
Please visit https://huggingface.co/spaces/sappho192/aihub-ja-ko-translator-demo

## Dependencies (PyPI)

- torch
- transformers
- fugashi
- unidic-lite

## Inference

```Python
from transformers import(
    EncoderDecoderModel,
    PreTrainedTokenizerFast,
    BertJapaneseTokenizer,
)

import torch

encoder_model_name = "cl-tohoku/bert-base-japanese-v2"
decoder_model_name = "skt/kogpt2-base-v2"

src_tokenizer = BertJapaneseTokenizer.from_pretrained(encoder_model_name)
trg_tokenizer = PreTrainedTokenizerFast.from_pretrained(decoder_model_name)

model = EncoderDecoderModel.from_pretrained("sappho192/aihub-ja-ko-translator")

text = "初めまして。よろしくお願いします。"

def translate(text_src):
    embeddings = src_tokenizer(text_src, return_attention_mask=False, return_token_type_ids=False, return_tensors='pt')
    embeddings = {k: v for k, v in embeddings.items()}
    output = model.generate(**embeddings, max_length=500)[0, 1:-1]
    text_trg = trg_tokenizer.decode(output.cpu())
    return text_trg

print(translate(text))
```

# Dataset

This model used datasets from 'The Open AI Dataset Project (AI-Hub, South Korea)'.  
All data information can be accessed through 'AI-Hub ([aihub.or.kr](https://www.aihub.or.kr))'.  
(**In order for a corporation, organization, or individual located outside of Korea to use AI data, etc., a separate agreement is required** with the performing organization and the Korea National Information Society agency(NIA). In order to export AI data, etc. outside the country, a separate agreement is required with the performing organization and the NIA. [Link](https://aihub.or.kr/intrcn/guid/usagepolicy.do?currMenu=151&topMenu=105))  

이 모델은 과학기술정보통신부의 재원으로 한국지능정보사회진흥원의 지원을 받아 구축된 데이터셋을 활용하여 수행된 연구입니다.  
본 모델에 활용된 데이터는 AI 허브([aihub.or.kr](https://www.aihub.or.kr))에서 다운로드 받으실 수 있습니다.  
(**국외에 소재하는 법인, 단체 또는 개인이 AI데이터 등을 이용하기 위해서는** 수행기관 등 및 한국지능정보사회진흥원과 별도로 합의가 필요합니다.  
**본 AI데이터 등의 국외 반출을 위해서는** 수행기관 등 및 한국지능정보사회진흥원과 별도로 합의가 필요합니다. [[출처](https://aihub.or.kr/intrcn/guid/usagepolicy.do?currMenu=151&topMenu=105)])

## Dataset list

The dataset used to train the model is merged following sub-datasets:  

- 027. 일상생활 및 구어체 한-중, 한-일 번역 병렬 말뭉치 데이터 [[Link](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=546)]
- 053. 한국어-다국어(영어 제외) 번역 말뭉치(기술과학) [[Link](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=71493)]
- 054. 한국어-다국어 번역 말뭉치(기초과학) [[Link](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=71496)]
- 055. 한국어-다국어 번역 말뭉치 (인문학) [[Link](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=71498)]
- 한국어-일본어 번역 말뭉치 [[Link](https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&dataSetSn=127)]

To reproduce the the merged dataset, you can use the code in below link:  
https://github.com/sappho192/aihub-translation-dataset

