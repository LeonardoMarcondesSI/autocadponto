# Pontos AutoCAD

Aplicativo desktop em português para conferir **área, perímetro e correspondência entre a planta e o memorial**, além de gerar scripts para AutoCAD **2D**. A conferência usa a tabela de coordenadas da planta; não extrai o contorno de um desenho DWG nem verifica estradas.

## Abrir

Baixe ou clone este repositório. Com Python 3.14 de 64 bits instalado no Windows, abra **Instalar.bat** para criar o ambiente `.venv` e instalar as dependências. Depois, abra **Iniciar.bat** para usar o aplicativo. Se o ambiente já estiver preparado, basta abrir **Iniciar.bat**. A versão testada foi Python 3.14.8 no Windows.

A instalação baixa bibliotecas Python. A leitura dos documentos é local. Os modelos padrão do RapidOCR vêm no pacote instalado; o app não envia fotos ou memoriais para serviços externos e não usa Tesseract.

## Fluxo de uso

1. **Tabela e contorno:** abra foto, PDF ou lista CSV/TXT. Também aceita a lista sem extensão do exemplo enviado. O layout de foto suportado é `Código | E | N | Altitude | Código do destino | Azimute | Distância`, com outras colunas à direita. A altitude é ignorada na saída 2D. A orientação automática tenta girar a foto; a borda da tabela é usada para corrigir perspectiva quando detectada.
2. Confira as linhas com a imagem. Dê duplo clique para corrigir um ponto; use as setas para reordenar. A prévia e o contorno seguem **a ordem da lista**, sem ordenar os identificadores automaticamente. A coluna Destino é usada nas comparações de trechos.
3. **Memorial:** abra uma ou várias páginas em PDF, imagem ou texto. Confira a ordem das páginas antes da leitura, ou cole o texto no painel. Clique em **Interpretar texto** depois de alterar o texto. São reconhecidos E/N ou latitude/longitude em graus, minutos e segundos, além dos trechos e totais do cabeçalho. Os registros e totais podem ser corrigidos na tela. O botão **Revisar códigos semelhantes** apresenta possíveis trocas de O/0 e pontuação para confirmação individual.
4. **Conferência:** ajuste as tolerâncias e clique em Conferir documentos. O topo mostra área e perímetro da planta, valores declarados no memorial e diferenças. O relatório separa comparação entre documentos, verificação das medidas pelas coordenadas, cobertura e ordem do contorno. Itens não interpretados aparecem como pendências.
5. Marque que conferiu valores, quantidade e ordem. Exporte os arquivos e abra-os pelo comando **SCRIPT** do AutoCAD, em um desenho configurado em metros.

## Área e perímetro na prévia

Na aba **Prévia do desenho**, o contorno fechado mostra a área total em **m² e hectares** e o perímetro em **metros**, calculados pelas coordenadas E/N na ordem da tabela. Os valores se atualizam ao importar, editar, remover ou reordenar pontos, reabrir um projeto e mudar as opções do contorno. A altitude não participa do cálculo.

Com **Fechar contorno** desmarcado, aparece somente o comprimento dos trechos abertos. Com **Gerar contorno** desmarcado, as medidas ficam indisponíveis. Coordenadas incompletas impedem totais parciais; posições repetidas, cruzamentos e sobreposições impedem a exibição de área/perímetro e recebem uma orientação na prévia. É aceita a repetição do primeiro vértice no final da lista.

Essas medidas são planas e pressupõem E/N em metros no mesmo sistema. A aba **Conferência** compara os totais com o memorial. A exportação do contorno verifica coordenadas, cruzamentos, sobreposições e a ordem em relação aos destinos informados. O botão **Organizar contorno pelos destinos** apresenta uma sequência sugerida para confirmação antes de alterar a tabela.

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
- Área e perímetro do contorno versus os totais declarados no memorial, com tolerâncias próprias.
- Identificações, próximos vértices, distâncias e azimutes diretamente entre planta e memorial. Cada campo recebe um resultado; dados ausentes não são considerados aprovados.
- Ordem do desenho versus destinos, fechamento, cruzamentos, sobreposições e repetição de posições.

Critérios iniciais ajustáveis: posição 0,02 m, distância 0,05 m, azimute 1 minuto, área 1,00 m² e perímetro 0,10 m. São critérios numéricos do app, não limites normativos. Um resultado “confere” corresponde somente ao item comparado.

Área e perímetro podem ser comparados numericamente sem configurar a conversão de latitude/longitude. Para comparar as posições do memorial geográfico com E/N, abra **Referência de coordenadas** e informe os sistemas dos documentos, por código EPSG ou datum/fuso/hemisfério. Nada é preenchido por suposição. A conversão usa `pyproj`, localmente, sem busca de grades pela rede; transformação ausente, sem precisão conhecida ou inadequada à tolerância fica pendente. Os valores originais são preservados.

Para comparar diretamente distâncias e azimutes, selecione **Grade da planta** somente quando o memorial declarar o mesmo tipo de medida. Quando o tipo não estiver informado, ou for geodésico/de terreno, o app exibe números e diferenças com estado pendente. Não aplica uma correção de escala ou de norte por suposição.

## Leitura e revisão

O memorial deve identificar os vértices como `vértice P-001` (ou ponto/marco). Aceita coordenadas `E ... N ...` ou `Lon: 45°25'47,648" W, Lat: 22°14'54,554" S`. Reconhece os formatos `azimute de 90°00' e distância de 100,00 m` e `90°00' e de 100,00 m até o vértice ...`, inclusive com continuação entre páginas. A repetição do vértice inicial ao encerrar a descrição não cria um ponto extra; diferenças nas coordenadas de fechamento são sinalizadas. Outras redações e manuscritos podem exigir edição.

Nas fotos de tabelas pautadas, o app procura os cabeçalhos e compara as orientações possíveis antes de ler cada célula. Leituras por célula e por imagem são confrontadas. Separadores de coordenadas com grupos de milhar e duas casas decimais podem ser padronizados, com registro do texto original. Não há troca automática entre letras e números. Se leituras confiáveis discordarem sobre um número, o campo fica vazio e pendente, evitando usar um valor incerto para calcular os totais.

Selecione uma linha e use **Ver linha selecionada** para ampliar o recorte da fonte. As alternativas reconhecidas aparecem junto ao texto original. Duplo clique permite corrigir os valores; marque **Conferi todos os campos desta linha** somente após revisar a linha inteira. As observações são preservadas se essa opção não for marcada.

OCR pode trocar números ou omitir linhas mesmo com confiança alta. Confira a quantidade de pontos, a ordem e os valores com a imagem. A aplicação não altera letras para dígitos silenciosamente. Números ambíguos como `123.456` devem ser informados como `123456` (inteiro) ou `123,456` (decimal). Se não conseguir ler um campo reconhecido, ele fica pendente. Uma linha completamente omitida pelo OCR pode não ser detectável automaticamente.

A leitura em lote adiciona as páginas na ordem selecionada; duplicatas precisam ser resolvidas antes de exportar. Durante a sessão, selecionar um ponto mostra a imagem correspondente quando disponível. As imagens não são embutidas no projeto salvo; reimporte a fonte para recuperar os recortes. Fotos maiores são reduzidas para limitar memória. Prefira imagens nítidas, próximas, alinhadas e com todas as bordas da tabela. Se grade e cabeçalhos não forem identificados, as coordenadas ficam pendentes em vez de serem atribuídas a colunas por suposição.

PDFs de tabela são renderizados para leitura; no memorial, texto digital é priorizado. PDFs mistos com texto e imagem na mesma página ainda podem exigir exportar a página como imagem. A análise automática de todo tipo de PDF permanece fora desta atualização.

## Desenvolvimento

O código fica em `pontos_autocad/`: dados básicos em `core.py`, células em `table_ocr.py`, memorial em `memorial.py`, conferência em `conference.py`, conversão em `georef.py`, geometria em `geometry.py`, leitura em `reader.py` e interface em `ui.py`. O Git ignora `.venv`, logs, a foto de teste e saídas geradas. Repositório do projeto: [LeonardoMarcondesSI/autocadponto](https://github.com/LeonardoMarcondesSI/autocadponto). Os exemplos incluídos são fictícios; mantenha fotos e documentos de trabalho fora do versionamento.

No VS Code, selecione `.venv/Scripts/python.exe`. Para instalar: `python -m pip install -r requirements.txt`. Para testar as regras: `python -m unittest discover -s tests -v`. O arquivo `requirements-lock.txt` registra também as dependências transitivas da instalação validada.

Bibliotecas: [RapidOCR](https://github.com/RapidAI/RapidOCR), [ONNX Runtime](https://onnxruntime.ai/), [Pillow](https://python-pillow.github.io/) e [PyMuPDF](https://pymupdf.readthedocs.io/). Referência: [scripts do AutoCAD](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Customization/files/GUID-95BB6824-0700-4019-9672-E6B502659E9E.htm). As bibliotecas mantêm suas próprias licenças; PyMuPDF é distribuído sob AGPL/comercial.
