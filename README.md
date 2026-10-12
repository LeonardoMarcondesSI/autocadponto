# Pontos AutoCAD

Aplicativo desktop em português para ler tabelas de coordenadas, conferir números de um memorial e gerar scripts para AutoCAD **2D**.

## Abrir

Na pasta do projeto, dê dois cliques em **Iniciar.bat**. Nesta máquina, o ambiente `.venv` já foi preparado. Para instalar outra cópia, use **Instalar.bat** com Python 3.14 de 64 bits instalado. A versão testada foi Python 3.14.8 no Windows.

A instalação baixa bibliotecas Python. A leitura dos documentos é local. Os modelos padrão do RapidOCR vêm no pacote instalado; o app não envia fotos ou memoriais para serviços externos e não usa Tesseract.

## Fluxo de uso

1. **Tabela e contorno:** abra foto, PDF ou lista CSV/TXT. Também aceita a lista sem extensão do exemplo enviado. O layout de foto suportado é `Código | E | N | Altitude | Código do destino | Azimute | Distância`, com outras colunas à direita. A altitude é ignorada na saída 2D. A orientação automática tenta girar a foto; a borda da tabela é usada para corrigir perspectiva quando detectada.
2. Confira as linhas com a imagem. Dê duplo clique para corrigir um ponto; use as setas para reordenar. A prévia e o contorno seguem **a ordem da lista**, sem ordenar os identificadores automaticamente. A coluna Destino é usada nas comparações de trechos.
3. **Memorial:** abra PDF, imagem ou texto, ou cole o texto no painel. PDFs com texto são extraídos diretamente; páginas digitalizadas passam por OCR. Clique em **Interpretar texto** depois de alterar o texto. Os registros também podem ser corrigidos ou adicionados na tabela ao lado.
4. **Conferência:** ajuste as tolerâncias e clique em Conferir documentos. É possível conferir as distâncias/azimutes impressos na própria tabela mesmo sem memorial. O relatório informa separadamente a ausência do memorial.
5. Marque que conferiu valores, quantidade e ordem. Exporte os arquivos e abra-os pelo comando **SCRIPT** do AutoCAD, em um desenho configurado em metros.

## Arquivos gerados

- `pontos_pontos.scr`: entidades POINT em X=E, Y=N, Z=0.
- `pontos_contorno.scr`: polilinha na ordem da tabela, aberta ou fechada conforme a opção.
- `pontos.csv`: identificadores, coordenadas e dados declarados dos trechos; separador `;` e vírgula decimal. Pode ser reimportado.
- Relatório CSV de conferência, salvo pela aba Conferência.
- Projeto `.pontos.json`, para guardar pontos, memorial, correções e critérios. A foto de prévia não é embutida no projeto; ela permanece no arquivo original.

O script usa comandos globais do AutoCAD, UCS World, espessura e elevação zero. Os pontos usam PDMODE=35/PDSIZE=-2; o contorno usa largura zero. Esses ajustes permanecem no desenho. As inserções suprimem captura de objetos com `_non`. Cada script agrupa o desenho em uma operação de UNDO. Os comandos foram conferidos por documentação e testes do texto gerado; a execução em uma instalação do AutoCAD ainda requer validação do usuário.

## O que a conferência calcula

- Coordenadas do memorial versus tabela: diferença de posição `sqrt((ΔE)² + (ΔN)²)`.
- Distância declarada versus distância plana calculada pelas coordenadas.
- Azimute declarado versus `atan2(ΔE, ΔN)`, contado no sentido horário a partir do norte da grade. A diferença considera a passagem 359° → 0° e é expressa em minutos de arco.
- Pontos ausentes, identificações repetidas na tabela, coordenadas incompletas e campos não interpretados aparecem como **pendências**.

Critérios iniciais ajustáveis: posição 0,02 m, distância 0,05 m e azimute 1 minuto. São critérios de comparação escolhidos para o app, não limites normativos. Todos os dados devem usar a mesma projeção/unidade; não há conversão de datum/fuso, latitude/longitude, distância de terreno ou azimute geodésico. Um resultado “confere” indica consistência numérica nos itens comparados, não valida o levantamento de campo.

## Formatos e limites da primeira versão

O memorial deve identificar os vértices como `vértice P-001` (ou ponto/marco), conter coordenadas explicitamente rotuladas `E ... N ...` e, para os trechos, expressões como `azimute de 90°00' e distância de 100,00 m até o vértice P-002`. Também aceita tabela/lista no formato do exemplo. Redações diferentes e manuscritos podem exigir edição; o app não garante interpretar todo tipo de memorial. Os exemplos fictícios em `exemplos/` permitem experimentar esse fluxo.

OCR pode trocar números ou omitir linhas mesmo com confiança alta. Confira a quantidade de pontos, a ordem e os valores com a imagem. A aplicação não altera letras para dígitos silenciosamente. Números ambíguos como `123.456` devem ser informados como `123456` (inteiro) ou `123,456` (decimal). Se não conseguir ler um campo reconhecido, ele fica pendente. Uma linha completamente omitida pelo OCR pode não ser detectável automaticamente.

A leitura em lote adiciona as páginas na ordem selecionada; duplicatas precisam ser resolvidas antes de exportar. A prévia mostra a última imagem importada (em PDF, a primeira página), e cada ponto guarda o nome da fonte e o texto reconhecido. Fotos maiores são reduzidas para limitar memória. Prefira recortes próximos da tabela e imagens nítidas.

## Desenvolvimento

O código fica em `pontos_autocad/`: regras em `core.py`, leitura em `reader.py`, interface em `ui.py`. O Git ignora `.venv`, logs, a foto de teste e saídas geradas. O repositório é local; nenhuma publicação no GitHub é feita.

No VS Code, selecione `.venv/Scripts/python.exe`. Para instalar: `python -m pip install -r requirements.txt`. Para testar as regras: `python -m unittest discover -s tests -v`. O arquivo `requirements-lock.txt` registra também as dependências transitivas da instalação validada.

Bibliotecas: [RapidOCR](https://github.com/RapidAI/RapidOCR), [ONNX Runtime](https://onnxruntime.ai/), [Pillow](https://python-pillow.github.io/) e [PyMuPDF](https://pymupdf.readthedocs.io/). Referência: [scripts do AutoCAD](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Customization/files/GUID-95BB6824-0700-4019-9672-E6B502659E9E.htm). As bibliotecas mantêm suas próprias licenças; PyMuPDF é distribuído sob AGPL/comercial.
