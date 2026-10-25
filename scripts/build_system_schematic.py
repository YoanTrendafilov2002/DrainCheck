"""Editable vector workflow plus matching presentation PNG and PDF.

Use the Codex bundled Python runtime. This diagram describes implemented paths;
it contains no simulated map or substituted terrain pixels.
"""
from pathlib import Path
from html import escape
import argparse,hashlib,json,math,re
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
import pypdfium2 as pdfium
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
IN_REPO=(ROOT/'backend').is_dir()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=ROOT/('docs' if IN_REPO else 'outputs'))
parser.add_argument('--guide',type=Path,default=ROOT/('docs/RISK_CALCULATION_GUIDE.md' if IN_REPO else 'outputs/sofia_explorer_app/docs/RISK_CALCULATION_GUIDE.md'))
parser.add_argument('--qa-dir',type=Path,default=ROOT/('data/cache/schematic_qa' if IN_REPO else 'work/schematic_qa'))
parser.add_argument('--font-dir',type=Path,default=Path('C:/Windows/Fonts'))
parser.add_argument('--simplified',action='store_true',help='Render the dark right-to-left overview with concise explanations and calculation context.')
args=parser.parse_args()
OUT=args.output_dir;OUT.mkdir(parents=True,exist_ok=True)
BASE=OUT/('DrainCheck_System_Schematic_Simple' if args.simplified else 'DrainCheck_System_Schematic')
W,H=(2560,1440) if args.simplified else (1920,1080)
FONT_DIR=args.font_dir
for key,file in [('Regular','segoeui.ttf'),('Semibold','seguisb.ttf'),('Bold','segoeuib.ttf')]:
    pdfmetrics.registerFont(TTFont(key,str(FONT_DIR/file)))
INK='#17343F'; MUTED='#526B74'; PAPER='#F5F7F6'; LINE='#D8E2E5'
TEAL='#087D80'; BLUE='#5263A5'; ORANGE='#B56125'

class Drawing:
    def __init__(self):
        self.svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
          '<title id="title">How DrainCheck works</title>',
          ('<desc id="desc">Dark right-to-left workflow: source data, processing and map layers. Terrain factors feed a relative ponding heatmap; flood records and buildings feed review priorities; assumed storm and blockage inputs feed local depression storage and baseline/clogged/change comparisons. Land exclusions, river context, archived rainfall and model limitations remain explicit.</desc>' if args.simplified else '<desc id="desc">Three parallel workflows show real terrain screening, categorical historical and building review, and an assumed rainfall and pipe blockage scenario using local terrain storage. River proximity and archived daily rainfall remain separate context.</desc>')]
        self.c=canvas.Canvas(str(BASE.with_suffix('.pdf')),pagesize=(W,H),pageCompression=1)
        self.c.setTitle('How DrainCheck works')
        self.c.setAuthor('DrainCheck')
        self.c.setSubject('Implemented Sofia flood-screening and comparative storm workflow v1.9')
        self.text_bounds=[]
    def rect(self,x,y,w,h,fill='#FFFFFF',stroke=LINE,r=16):
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"/>')
        self.c.setFillColor(HexColor(fill));self.c.setStrokeColor(HexColor(stroke));self.c.setLineWidth(1)
        self.c.roundRect(x,H-y-h,w,h,r,stroke=int(stroke!=fill),fill=1)
    def line(self,x1,y1,x2,y2,color=LINE,width=2,dash=False):
        self.svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"'+(' stroke-dasharray="5 5"' if dash else '')+'/>')
        self.c.setStrokeColor(HexColor(color));self.c.setLineWidth(width);self.c.setDash([5,5] if dash else [])
        self.c.line(x1,H-y1,x2,H-y2);self.c.setDash([])
    def polygon(self,points,color):
        self.svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="{color}"/>')
        self.c.setFillColor(HexColor(color));p=self.c.beginPath();p.moveTo(points[0][0],H-points[0][1])
        for x,y in points[1:]:p.lineTo(x,H-y)
        p.close();self.c.drawPath(p,stroke=0,fill=1)
    def arrow(self,x1,y1,x2,y2,color=MUTED):
        self.line(x1,y1,x2-7,y2,color,2)
        self.polygon([(x2,y2),(x2-10,y2-6),(x2-10,y2+6)],color)
    def text(self,x,y,text,size=21,weight='Regular',color=INK):
        width=pdfmetrics.stringWidth(text,weight,size)
        assert x>=0 and x+width<=W-24,(text,x,width)
        self.text_bounds.append([x,y,size,width,text])
        self.svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="'+{'Regular':'400','Semibold':'600','Bold':'700'}[weight]+'">'+escape(text)+'</text>')
        self.c.setFont(weight,size);self.c.setFillColor(HexColor(color));self.c.drawString(x,H-y,text)
    def lines(self,x,y,text,maxwidth,size=21,leading=29,color=MUTED,weight='Regular'):
        yy=y
        for para in text.split('\n'):
            current=''
            for word in para.split():
                trial=(current+' '+word).strip()
                if current and pdfmetrics.stringWidth(trial,weight,size)>maxwidth:
                    self.text(x,yy,current,size,weight,color);yy+=leading;current=word
                else:current=trial
            if current:self.text(x,yy,current,size,weight,color);yy+=leading
        return yy
    def card(self,x,y,w,h,label,title,color,body=None,title_size=25):
        self.rect(x,y,w,h)
        self.rect(x,y,5,h,color,color,2)
        self.text(x+24,y+31,label,14,'Bold',color)
        self.text(x+24,y+65,title,title_size,'Semibold')
        if body:self.lines(x+24,y+98,body,w-48,20,27)
    def finish(self):
        self.svg.append('</svg>');BASE.with_suffix('.svg').write_text('\n'.join(self.svg),encoding='utf-8')
        self.c.showPage();self.c.save()

def draw_detailed(d):
    d.rect(0,0,W,H,PAPER,PAPER,0)
    d.text(64,49,'DRAINCHECK  /  IMPLEMENTED WORKFLOW',15,'Bold',TEAL)
    d.text(64,105,'How DrainCheck works',46,'Bold')
    d.text(64,145,'Real Sofia data, three separate analytical views, one layered map.',23,'Regular',MUTED)
    d.rect(1452,55,404,64,'#E7F0EF','#D0E0DD',12)
    d.text(1473,82,'1 m GROUND INSPECTION',16,'Bold',TEAL)
    d.text(1473,105,'5 m ANALYSIS  ·  VERSION 1.9',16,'Semibold',MUTED)
    for x,title in [(64,'SOURCE DATA AND USER CHOICES'),(454,'PROCESSING AND ASSUMPTIONS'),(1494,'MAPS AND COMPARISONS')]:
        d.text(x,194,title,15,'Bold',MUTED)

    # Path 1: original descriptors and display. No rain or river proximity enters P.
    d.card(64,216,350,150,'01  TERRAIN','Municipal 1 m DTM',TEAL,
           'Real ground elevations\nBaltic 1982 height datum',25)
    d.card(454,216,470,150,'REAL TERRAIN','Align to the 5 m grid',TEAL,
           'Elevation, depression fill depth,\nslope and contributing area.',25)
    d.card(964,216,490,150,'RELATIVE INDICATOR','Calculate ponding signal P',TEAL,
           '0–100 rank of positive fill depth.\nZero where there is no depression.',25)
    d.card(1494,216,362,150,'TERRAIN VIEW','Continuous heatmap',TEAL,
           'Original P values; a relative\nsignal, not flood probability.',24)
    for a,b in [(414,454),(924,964),(1454,1494)]:d.arrow(a+5,291,b-5,291,TEAL)

    # Path 2: discrete evidence precedence, kept separate from original P.
    d.card(64,394,350,150,'02  EXPOSURE AND EVIDENCE','Past floods + buildings',BLUE,
           '136 observed flood polygons\nCadastral building footprints',24)
    d.card(454,394,1000,150,'CATEGORICAL RULES','Review terrain alongside actual flood evidence',BLUE,
           'Use P, observed flood footprints and potential building intersection.\nHistorical categories take precedence over lower terrain categories.',26)
    d.card(1494,394,362,150,'EVIDENCE VIEW','Review priorities',BLUE,
           'Category map plus independent\nobserved-flood overlays.',25)
    d.arrow(419,469,449,469,BLUE);d.arrow(1459,469,1489,469,BLUE)
    d.line(1209,366,1209,382,BLUE,2);d.polygon([(1209,394),(1203,383),(1215,383)],BLUE)
    d.text(1222,387,'P',15,'Bold',BLUE)

    # Path 3: assumed water balance followed by constrained terrain storage.
    d.card(64,572,350,278,'03  EDITABLE WHAT IF','Area, pipes and storm',ORANGE,None,24)
    d.lines(88,669,'Draw an area. Select existing pipes. Set rain, duration, blockage and assumed drainage removal.',302,20,28)
    d.rect(88,765,302,60,'#FCF1E6','#F0D9C6',9)
    d.text(103,789,'EVENT RAINFALL SLIDER',13,'Bold',ORANGE)
    d.line(104,807,372,807,'#D8AD87',5);d.line(104,807,188,807,ORANGE,5)
    d.rect(181,800,14,14,ORANGE,ORANGE,7)

    d.card(454,572,470,278,'ASSUMED WATER BALANCE','Compare available drainage',ORANGE,None,24)
    d.text(478,671,'Effective rain = rainfall × runoff coefficient',19,'Regular',MUTED)
    d.text(478,710,'Baseline: full assumed removal',22,'Semibold')
    d.text(478,745,'Clogged: reduced removal',22,'Semibold')
    d.lines(478,782,'Capacity loss applies only inside the selected existing-pipe buffer. Excess runoff is measured in mm.',422,20,27)

    d.card(964,572,490,278,'REUSES REAL 5 m TERRAIN','Estimate local ponding depth',ORANGE,None,24)
    d.lines(988,671,'Within each terrain depression, store only its locally generated excess runoff using actual bed elevations and fill depth.',442,20,28)
    d.lines(988,768,'Cap storage at the spill level. Report overflow separately. Leave runoff on non-depression land unallocated.',442,20,28)

    d.card(1494,572,362,278,'STORM COMPARISON','Baseline / clogged / change',ORANGE,None,22)
    d.text(1518,676,'Estimated depth',22,'Semibold');d.text(1800,676,'m',21,'Bold',ORANGE)
    d.text(1518,719,'Unremoved runoff',22,'Semibold');d.text(1780,719,'mm',21,'Bold',ORANGE)
    d.text(1518,762,'Water volumes',22,'Semibold');d.text(1790,762,'m³',21,'Bold',ORANGE)
    d.lines(1518,805,'Stored · overflow · unallocated',314,19,26)
    for a,b in [(414,454),(924,964),(1454,1494)]:d.arrow(a+5,711,b-5,711,ORANGE)

    # Supporting rules do not become a fourth composite flood probability.
    d.rect(64,879,560,122,'#EAF2EC','#D5E2D8',12)
    d.text(86,908,'SHARED LAND EXCLUSIONS',15,'Bold','#38754B')
    d.lines(86,939,'Mapped water and uncertain terrain are excluded. Mapped greens fully absorb rain by the chosen assumption; source observations remain separate.',516,19,25)
    d.rect(648,879,620,122,'#EAF0F7','#D4DFEB',12)
    d.text(670,908,'RIVER PROXIMITY CONTEXT',15,'Bold','#416D9A')
    d.lines(670,939,'18 mapped river footprints + 19 assessment reaches → distance threshold → river-adjacent / away context. Proximity does not determine flood cause.',576,19,25)
    d.rect(1292,879,564,122,'#EEF0F3','#DCE1E5',12)
    d.text(1314,908,'SUPPLEMENTAL MAP LAYERS',15,'Bold',MUTED)
    d.lines(1314,939,'Archived daily rain, official assessments and infrastructure inventory remain separate context. Archived rain does not drive the storm slider.',520,19,25)

    d.line(64,1021,1856,1021,LINE,1)
    d.text(64,1054,'Comparative screening, not a calibrated flood forecast. Scenario omits dynamic flow routing, pipe hydraulics and river-level simulation.',19,'Regular',MUTED)
    d.text(1709,1054,'25 OCT 2026',15,'Semibold',MUTED)

def draw_simple(d):
    """Follow the supplied source-right, processing-centre, layers-left template."""
    bg='#07131C';white='#F0F8FC';soft='#A6C4D0';dark='#042B3A'
    colors=['#0796B5','#32B7C4','#71D8D5']
    d.rect(0,0,W,H,bg,bg,0)
    d.text(64,67,'DRAINCHECK',19,'Bold',colors[2])
    d.text(64,135,'How DrainCheck works',54,'Bold',white)
    d.text(64,180,'Real terrain, flood evidence and editable storm scenarios.',25,'Regular',soft)
    d.rect(2040,78,456,68,'#102B36','#20434D',12)
    d.text(2063,121,'1 m inspection  ·  5 m analysis',25,'Semibold',colors[2])
    for x,label in [(380,'Layers'),(960,'Processing'),(2080,'Source data')]:
        d.text(x,230,label,28,'Semibold',white)

    def box(x,y,w,h,label,title,body,color,title_size=29,body_size=21):
        d.rect(x,y,w,h,color,color,16)
        for text,size,font in [(label,15,'Bold'),(title,title_size,'Semibold')]+[(s,body_size,'Regular') for s in body]:
            assert pdfmetrics.stringWidth(text,font,size)<=w-40,(text,w)
        d.text(x+20,y+30,label,15,'Bold',dark)
        d.text(x+20,y+72,title,title_size,'Semibold',dark)
        for i,line in enumerate(body):d.text(x+20,y+110+i*32,line,body_size,'Regular',dark)

    def left_arrow(x1,y,x2):
        d.line(x1,y,x2+13,y,white,4)
        d.polygon([(x2,y),(x2+14,y-9),(x2+14,y+9)],white)

    # Terrain: slope/area diagnostics are retained without feeding the P formula.
    y=260;c=colors[0]
    box(2080,y,416,150,'01  REAL TERRAIN','Municipal 1 m DTM',
        ['Baltic 1982 ground elevations.'],c)
    box(1490,y,450,150,'ALIGNED 5 m GRID','Terrain factors',
        ['Elevation · fill depth · slope · flow area'],c,body_size=20)
    box(960,y,450,150,'PERCENTILE RANK','Ponding signal P',
        ['Rank positive fill depth; zero if none.'],c,body_size=20)
    box(380,y,440,150,'TERRAIN LAYER','Continuous heatmap',
        ['P: 0–100 · not flood probability.'],c)
    for right,left in [(2060,1960),(1470,1430),(940,840)]:left_arrow(right,y+75,left)
    d.text(380,456,'P uses fill depth only; slope and upstream contributing area remain diagnostics.',21,'Regular',soft)

    # P is an additional input to review classes, not overwritten by them.
    d.line(1185,410,1185,505,white,3,dash=True)
    d.polygon([(1185,520),(1177,505),(1193,505)],white)
    d.text(1204,487,'P',20,'Bold',colors[1])
    y=520;c=colors[1]
    box(2080,y,416,150,'02  OBSERVED / MAPPED','Past floods + buildings',
        ['136 flood polygons + cadastral footprints.'],c,title_size=27,body_size=18)
    box(960,y,980,150,'SEPARATE REVIEW RULES','Combine P, flood evidence and building overlap',
        ['Historical categories override lower terrain classes; buildings flag potential overlap.'],c,title_size=29,body_size=21)
    box(380,y,440,150,'EVIDENCE LAYERS','Review priorities',
        ['Independent historical-flood overlays.'],c,body_size=20)
    for right,left in [(2060,1960),(940,840)]:left_arrow(right,y+75,left)
    d.text(380,719,'History changes review categories; it does not change the terrain heatmap.',21,'Regular',soft)

    # Scenario: assumed water balance, reduced removal, then real local storage.
    y=820;c=colors[2]
    box(2080,y,416,210,'03  USER-SET SCENARIO','Area + existing pipes',
        ['Draw area; choose pipes and storm.',
         'Drainage and blockage are assumed.'],c,title_size=28,body_size=20)
    box(1490,y,450,210,'ASSUMED WATER BALANCE','Excess runoff',
        ['Baseline: max(0, rain×c − rate×min/60)',
         'Clogged: rate×(1−b/100) in pipe buffer.',
         'Baseline removal applies elsewhere.'],c,body_size=19)
    box(960,y,450,210,'USES REAL 5 m TERRAIN','Local depression storage',
        ['Real bed + fill depth; cap at spill level.',
         'Store each depression’s local runoff.'],c,title_size=27,body_size=20)
    box(380,y,440,210,'STORM LAYERS','Baseline / clogged / change',
        ['Est. depth (m) · excess runoff (mm)',
         'Stored · overflow · unallocated (m³)'],c,title_size=26,body_size=20)
    for right,left in [(2060,1960),(1470,1430),(940,840)]:left_arrow(right,y+105,left)
    d.text(380,1078,'Overflow is not routed; runoff on zero-fill land remains unallocated.',21,'Regular',soft)
    d.text(380,1120,'Inputs: rain (mm) · duration (min) · runoff coefficient c · assumed drainage rate (mm/h) · blockage b (%) · pipe buffer (m)',21,'Regular',soft)

    # All three layer groups feed the same map; no framework claim is made.
    d.line(300,335,300,925,white,4)
    for yy in [335,595,925]:d.line(300,yy,380,yy,white,4)
    left_arrow(300,595,245)
    d.rect(64,515,170,160,'#102B36','#2B707D',24)
    d.text(100,597,'DC',64,'Bold',colors[2])
    d.text(112,639,'MAP',18,'Bold',white)
    d.text(64,721,'DrainCheck',25,'Semibold',white)

    # Independent context is explicit, without turning it into flood causation.
    panels=[
      (64,770,'LAND RULES',
       ['Exclude mapped water and uncertain terrain.',
        'Assume mapped greens absorb all rain.']),
      (875,770,'RIVER CONTEXT',
       ['River distance: adjacent / away context.',
        'Proximity does not establish flood cause.']),
      (1686,810,'SUPPLEMENTAL LAYERS',
       ['Archived daily rain, assessments and infrastructure.',
        'Archive rain does not set the storm slider.']),
    ]
    for x,w,label,body in panels:
        d.rect(x,1165,w,155,'#10232E','#23404D',14)
        d.text(x+22,1204,label,18,'Bold',colors[2])
        for i,line in enumerate(body):d.text(x+22,1248+i*34,line,22,'Regular',soft)
    d.line(64,1356,2496,1356,'#23404D',1)
    d.text(64,1400,'Comparative screening and local storage estimates; no dynamic routing, sewer hydraulics or river-level simulation.',24,'Regular',white)


d=Drawing()
draw_simple(d) if args.simplified else draw_detailed(d)

d.finish()

# Export and inspect the same vector PDF, avoiding platform SVG-font drift.
pdf=pdfium.PdfDocument(str(BASE.with_suffix('.pdf')))
scale=1.5 if args.simplified else 2
page=pdf[0];bitmap=page.render(scale=scale);bitmap.to_pil().save(BASE.with_suffix('.png'))
qa=args.qa_dir;qa.mkdir(parents=True,exist_ok=True)
page.render(scale=1).to_pil().save(qa/'schematic-preview.png')
reader=PdfReader(str(BASE.with_suffix('.pdf')));assert len(reader.pages)==1
text=' '.join(('\n'.join(p.extract_text() or '' for p in reader.pages)).split())
tokens = (['Municipal 1 m DTM','Baltic 1982','Ponding signal P','zero if none','upstream contributing area','136 flood polygons','cadastral footprints','Historical categories override','rate×min/60','duration (min)','(1−b/100)','Baseline removal applies elsewhere','pipe buffer','spill level','local runoff','zero-fill','unallocated','runoff coefficient','blockage b (%)','greens absorb all rain','RIVER CONTEXT','does not establish flood cause','Archived daily rain','does not set the storm slider','no dynamic routing'] if args.simplified else ['Municipal 1 m DTM','136 observed flood polygons','Capacity loss','spill level','RIVER PROXIMITY','does not determine flood cause','Archived rain does not drive','unallocated'])
for token in tokens:
    assert token in text,token
receipt={'title':'How DrainCheck works','canvas':[W,H],'png_pixels':[int(W*scale),int(H*scale)],
 'layout':'dark source-right template' if args.simplified else 'detailed',
 'one_page_pdf':True,'source_guide':'docs/RISK_CALCULATION_GUIDE.md','version':'1.9',
 'source_guide_sha256':hashlib.sha256(args.guide.read_bytes()).hexdigest(),
 'files':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [BASE.with_suffix(s) for s in ['.svg','.pdf','.png']]},
 'semantic_checks':('PASS: terrain factors and P, historical precedence/buildings, storm inputs and assumed removal, local storage/spill/overflow/unallocated, exclusions, river proximity, independent rainfall and hydraulic limits retained' if args.simplified else 'PASS: separate P, categorical review and hypothetical storm paths; explicit assumptions, units and independent river/archive context'),
 'visual_qa':'Pending rendered inspection'}
(qa/'verification.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps(receipt))
