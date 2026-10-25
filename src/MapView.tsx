import {useEffect,useRef} from 'react';
import maplibregl,{Map as GLMap,Marker,RasterTileSource,VectorTileSource,GeoJSONSource} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-csp-worker.js?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import type {AppState,Scale,BuildingsMeta,HistorySurveyMeta,RainfallMeta,MapFocus} from './types';
maplibregl.setWorkerUrl(workerUrl);
const emptyStyle:any={version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#dce5de'}}]};
function styleFor(s:AppState,meta:any){return s.basemap==='none'?emptyStyle:s.basemap==='dark'?'https://tiles.openfreemap.org/styles/dark':s.basemap==='custom'?(/^https?:\/\//.test(s.customBasemap)?s.customBasemap:emptyStyle):meta.basemap_style;}
function rainfallTileUrl(s:AppState,rain:RainfallMeta,renderer:string){const threshold=s.rainProduct==='merged_250m'&&s.rainThreshold?`&threshold=${s.rainThresholdMm}`:'';return `${location.origin}/api/rainfall/tiles/${s.rainProduct}/{z}/{x}/{y}.png?smoothing=${s.rainSmoothing}${threshold}&v=${rain.revision}&r=${renderer}`;}
function historyFilter(s:AppState):any{const clauses:any[]=['all'];if(s.historyMechanism!=='all')clauses.push(['==',['coalesce',['get','mechanism'],'unknown'],s.historyMechanism]);if(s.historyConfidence!=='all')clauses.push(['==',['coalesce',['get','mechanism_confidence'],'unknown'],s.historyConfidence]);return clauses.length>1?clauses:null;}
function screeningTileUrl(s:AppState,terrain:any,review:any,renderer:string){return s.riskMode==='review'?`${location.origin}/api/refinement/tiles/{z}/{x}/{y}.png?v=${review?.revision}&r=${renderer}`:`${location.origin}/api/pluvial/${s.riskMode}/{z}/{x}/{y}.png?v=${terrain?.revision}&r=${renderer}`;}
export function MapView({state,meta,pluvialMeta,refinementMeta,buildingsMeta,cadastreMeta,historySurveyMeta,assessmentMeta,rainfallMeta,focusTarget,scale,onView,onInspect,onStatus,selected}: {state:AppState;meta:any;pluvialMeta:any;refinementMeta:any;buildingsMeta:BuildingsMeta|null;cadastreMeta:BuildingsMeta|null;historySurveyMeta:HistorySurveyMeta|null;assessmentMeta:any;rainfallMeta:RainfallMeta|null;focusTarget:MapFocus|null;scale:Scale|null;onView:(view:any,bounds:number[])=>void;onInspect:(lon:number,lat:number,feature?:any)=>void;onStatus:(s:string,error?:boolean)=>void;selected:any}){
  const container=useRef<HTMLDivElement>(null),map=useRef<GLMap|null>(null),marker=useRef<Marker|null>(null);
  const latest=useRef({state,meta,pluvialMeta,refinementMeta,buildingsMeta,cadastreMeta,historySurveyMeta,assessmentMeta,rainfallMeta,scale,onView,onInspect,onStatus});latest.current={state,meta,pluvialMeta,refinementMeta,buildingsMeta,cadastreMeta,historySurveyMeta,assessmentMeta,rainfallMeta,scale,onView,onInspect,onStatus};
  const historyDataUrl=useRef('');
  const assessmentDataUrl=useRef('');
  const stationsDataUrl=useRef('');
  const buildingZoomVisible=state.zoom>=(buildingsMeta?.minzoom??13);
  const cadastreZoomVisible=state.zoom>=(cadastreMeta?.minzoom??13);
  const lastStyle=useRef(state.basemap+state.customBasemap),ready=useRef(false);
  const hadError=useRef(false);
  function setup(m:GLMap){
    const {state:s,meta,pluvialMeta,refinementMeta,buildingsMeta,cadastreMeta,historySurveyMeta,assessmentMeta,rainfallMeta,scale}=latest.current;const v=meta.revision;const origin=window.location.origin;
    const vector=(kind:string,extra='')=>[`${origin}/api/vector/${kind}/{z}/{x}/{y}.pbf?v=${v}&r=${meta.renderer_revision||'v1'}${extra}`];
    const before=m.getStyle().layers?.find(l=>l.type==='symbol')?.id;
    const overlayBefore=(ids:string[])=>ids.find(id=>m.getLayer(id))||before;
    if(s.terrain&&s.opacity>0&&!m.getSource('terrain')&&meta.terrain_available&&scale){
      m.addSource('terrain',{type:'raster',tileSize:256,tiles:[`${origin}/api/raster/${scale.id}/{z}/{x}/{y}.png?v=${v}&r=${meta.renderer_revision||'v1'}`],minzoom:5,maxzoom:20,attribution:'SofiaPlan DTM · Baltic 1982'});
      m.addLayer({id:'terrain',type:'raster',source:'terrain',layout:{visibility:'visible'},paint:{'raster-opacity':s.opacity,'raster-resampling':'linear','raster-fade-duration':0}},overlayBefore(['rainfall','hillshade','pluvial','green-fill','route-existing','points']));
    }
    if(s.hillshade&&!m.getSource('hillshade')&&meta.terrain_available){
      m.addSource('hillshade',{type:'raster',tileSize:256,tiles:[`${origin}/api/hillshade/{z}/{x}/{y}.png?v=${v}&r=${meta.renderer_revision||'v1'}`],minzoom:5,maxzoom:20,attribution:'SofiaPlan DTM · Baltic 1982'});
      m.addLayer({id:'hillshade',type:'raster',source:'hillshade',layout:{visibility:'visible'},paint:{'raster-opacity':.22,'raster-fade-duration':0}},overlayBefore(['pluvial','green-fill','history-survey-fill','cadastre-fill','buildings-fill','route-existing','points']));
    }
    if(s.rain&&s.rainOpacity>0&&rainfallMeta?.available&&!m.getSource('rainfall')){
      const extents=Object.values(rainfallMeta.products||{}).map((p:any)=>p.bbox).filter((b:any)=>Array.isArray(b)&&b.length===4);
      const bounds=extents.length?[Math.min(...extents.map(b=>b[0])),Math.min(...extents.map(b=>b[1])),Math.max(...extents.map(b=>b[2])),Math.max(...extents.map(b=>b[3]))] as [number,number,number,number]:undefined;
      m.addSource('rainfall',{type:'raster',tileSize:256,tiles:[rainfallTileUrl(s,rainfallMeta,meta.renderer_revision||'v1')],bounds,minzoom:5,maxzoom:20,attribution:'Daily rainfall · OPERA / Weather Underground · 2025-06-27'});
      m.addLayer({id:'rainfall',type:'raster',source:'rainfall',layout:{visibility:'visible'},paint:{'raster-opacity':s.rainOpacity,'raster-resampling':'nearest','raster-fade-duration':0}},overlayBefore(['hillshade','pluvial','green-fill','history-survey-fill','cadastre-fill','buildings-fill','route-existing','points']));
    }
    if(!m.getSource('green')){
      m.addSource('green',{type:'vector',tiles:vector('green',`&display=${s.green==='all'?'all':'subset'}`),maxzoom:18,attribution:'Green areas · source 2020'});
      m.addLayer({id:'green-fill',source:'green','source-layer':'green',type:'fill',paint:{'fill-color':'#52c468','fill-opacity':s.risk?.06:.19},layout:{visibility:s.green==='off'?'none':'visible'}},before);
      m.addLayer({id:'green-outline',source:'green','source-layer':'green',type:'line',paint:{'line-color':'#338f52','line-width':.85,'line-opacity':s.risk?.55:.8},layout:{visibility:s.green==='off'?'none':'visible'}},before);
    }
    if(s.risk&&s.riskOpacity>0&&(s.riskMode==='review'?refinementMeta?.available:pluvialMeta?.available)&&!m.getSource('pluvial')){
      m.addSource('pluvial',{type:'raster',tileSize:256,tiles:[screeningTileUrl(s,pluvialMeta,refinementMeta,meta.renderer_revision||'v1')],minzoom:5,maxzoom:20,attribution:'Sofia evidence review / terrain screening · unvalidated · 5 m'});
      m.addLayer({id:'pluvial',type:'raster',source:'pluvial',layout:{visibility:'visible'},paint:{'raster-opacity':s.riskOpacity,'raster-resampling':'nearest','raster-fade-duration':0}},m.getLayer('green-outline')?'green-outline':before);
    }
    if(s.historySurvey&&historySurveyMeta?.available&&!m.getSource('history-survey')){
      historyDataUrl.current=`${origin}/api/history/zones.geojson?v=${historySurveyMeta.revision}&r=${meta.renderer_revision||'v1'}`;
      m.addSource('history-survey',{type:'geojson',data:historyDataUrl.current,attribution:'SofiaPlan · archived drone flood survey'});
      const beforeSurvey=overlayBefore(['cadastre-fill','buildings-fill','route-existing','points']);
      const surveyFilter=historyFilter(s),filterProps=surveyFilter?{filter:surveyFilter}:{};
      m.addLayer({id:'history-survey-fill',source:'history-survey',type:'fill',...filterProps,layout:{visibility:'visible'},paint:{'fill-color':'#3568bc','fill-opacity':s.historyPriority ? .22 : .07}},beforeSurvey);
      m.addLayer({id:'history-survey-outline',source:'history-survey',type:'line',...filterProps,layout:{visibility:'visible'},paint:{'line-color':'#376bc2','line-width':s.historyPriority?3:1.8,'line-opacity':.95,...(s.historyPriority?{}:{'line-dasharray':[3,1.5]})}},beforeSurvey);
    }
    if(s.assessmentOverlay&&assessmentMeta?.available&&!m.getSource('flood-assessment')){
      assessmentDataUrl.current=`${origin}/api/flood-assessment/geojson?v=${assessmentMeta.revision}`;
      m.addSource('flood-assessment',{type:'geojson',data:assessmentDataUrl.current,attribution:'Official flood assessment · source geometries'});
      const beforeAssessment=overlayBefore(['history-survey-fill','cadastre-fill','buildings-fill','route-existing','points','rain-stations-ok','rain-stations-rejected']);
      const levelColor:any=['match',['get','assessment_level'],'high','#d84b4b','medium','#ed9a3f','low','#e3ce65','#8ca2ac'];
      const mechanismColor:any=['match',['get','mechanism'],'pluvial','#37b9ae','river','#4e8fdd','mixed','#a785d1','infrastructure','#d5a452','#a2a9b2'];
      m.addLayer({id:'assessment-zone-fill',source:'flood-assessment',type:'fill',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':levelColor,'fill-opacity':.06}},beforeAssessment);
      m.addLayer({id:'assessment-zone-outline',source:'flood-assessment',type:'line',filter:['==',['geometry-type'],'Polygon'],paint:{'line-color':levelColor,'line-width':2.4,'line-dasharray':[1.5,1],'line-opacity':.95}},beforeAssessment);
      m.addLayer({id:'assessment-reach',source:'flood-assessment',type:'line',filter:['==',['geometry-type'],'LineString'],paint:{'line-color':'#6aadd6','line-width':2.8,'line-dasharray':[2,1],'line-opacity':.9}},beforeAssessment);
      m.addLayer({id:'assessment-identifier',source:'flood-assessment',type:'circle',filter:['==',['geometry-type'],'Point'],paint:{'circle-color':mechanismColor,'circle-radius':5,'circle-stroke-color':'#183849','circle-stroke-width':1.5}},beforeAssessment);
    }
    if(s.cadastre&&cadastreMeta?.available&&m.getZoom()>=(cadastreMeta.minzoom??13)&&!m.getSource('cadastre-buildings')){
      const minzoom=cadastreMeta.minzoom??13;
      m.addSource('cadastre-buildings',{type:'vector',tiles:[`${origin}/api/cadastre/tiles/{z}/{x}/{y}.pbf?v=${cadastreMeta.revision}&r=${meta.renderer_revision||'v1'}`],bounds:cadastreMeta.coverage_bbox_wgs84,minzoom,maxzoom:19,attribution:cadastreMeta.source_label||'Cadastral building outlines'});
      const beforeCadastre=overlayBefore(['buildings-fill','route-existing','points','rain-stations-ok','rain-stations-rejected']);
      m.addLayer({id:'cadastre-fill',source:'cadastre-buildings','source-layer':'buildings',type:'fill',minzoom,layout:{visibility:'visible'},paint:{'fill-color':'#efbc61','fill-opacity':.08}},beforeCadastre);
      m.addLayer({id:'cadastre-outline',source:'cadastre-buildings','source-layer':'buildings',type:'line',minzoom,layout:{visibility:'visible'},paint:{'line-color':'#aa741b','line-width':['interpolate',['linear'],['zoom'],13,.8,17,1.6],'line-opacity':.95}},beforeCadastre);
    }
    if(s.buildings&&buildingsMeta?.available&&m.getZoom()>=(buildingsMeta.minzoom??13)&&!m.getSource('buildings')){
      const minzoom=buildingsMeta.minzoom??13;
      const measuredHeight=buildingsMeta.height?.available&&buildingsMeta.height.semantics==='height_above_ground_m';
      m.addSource('buildings',{type:'vector',tiles:[`${origin}/api/buildings/tiles/{z}/{x}/{y}.pbf?v=${buildingsMeta.revision}&r=${meta.renderer_revision||'v1'}`],bounds:buildingsMeta.coverage_bbox_wgs84,minzoom,maxzoom:19,attribution:buildingsMeta.source_label||'Building source context'});
      const beforeBuildings=overlayBefore(['route-existing','points']);
      m.addLayer({id:'buildings-fill',source:'buildings','source-layer':'buildings',type:'fill',minzoom,layout:{visibility:'visible'},paint:{'fill-color':'#d9e1e5','fill-opacity':.42}},beforeBuildings);
      m.addLayer({id:'buildings-outline',source:'buildings','source-layer':'buildings',type:'line',minzoom,layout:{visibility:'visible'},paint:{'line-color':'#263e4d','line-width':['interpolate',['linear'],['zoom'],13,.6,17,1.2],'line-opacity':.8}},beforeBuildings);
      if(measuredHeight)m.addLayer({id:'buildings-extrusion',source:'buildings','source-layer':'buildings',type:'fill-extrusion',minzoom,filter:['>', ['number',['get','height_m'],0],0],layout:{visibility:s.buildings3d?'visible':'none'},paint:{'fill-extrusion-color':'#acb8c4','fill-extrusion-height':['number',['get','height_m'],0],'fill-extrusion-base':0,'fill-extrusion-opacity':.75,'fill-extrusion-vertical-gradient':true}},beforeBuildings);
    }
    if(!m.getSource('routes')){
      m.addSource('routes',{type:'vector',tiles:vector('routes','&zone='+s.zone),maxzoom:18,attribution:'Supplied sewer routes · source 2009'});
      [['existing','#00e5ff'],['planned','#ff4dce'],['open','#ffeb3b']].forEach(([status,color])=>{
        m.addLayer({id:'route-casing-'+status,source:'routes','source-layer':'routes',type:'line',filter:['==',['get','status'],status],
          layout:{'line-cap':'round','line-join':'round',visibility:s.statuses.includes(status)?'visible':'none'},
          paint:{'line-color':'#15333d','line-opacity':.78,'line-width':['interpolate',['linear'],['zoom'],9,2.6,16,5.6],...(status==='planned'?{'line-dasharray':[2,1.4]}:{})}} as any);
        m.addLayer({id:'route-'+status,source:'routes','source-layer':'routes',type:'line',filter:['==',['get','status'],status],
          layout:{'line-cap':'round','line-join':'round',visibility:s.statuses.includes(status)?'visible':'none'},
          paint:{'line-color':color,'line-width':['interpolate',['linear'],['zoom'],9,1.3,16,3.6],...(status==='planned'?{'line-dasharray':[2,1.4]}:{})}} as any);
      });
    }
    if(s.points.length&&!m.getSource('points')){
      m.addSource('points',{type:'vector',tiles:vector('points','&categories='+s.points.join(',')),maxzoom:19});
      const colours:any[]=['match',['get','category']];meta.config.infrastructure.categories.forEach((c:any)=>colours.push(c.code===null?'missing':String(c.code),c.color));colours.push('#ffffff');
      m.addLayer({id:'points',type:'circle',source:'points','source-layer':'points',filter:['in',['get','category'],['literal',s.points]],paint:{'circle-color':colours,'circle-radius':['interpolate',['linear'],['zoom'],10,1.4,17,4],'circle-stroke-color':'#12313c','circle-stroke-width':.5}} as any);
    }
    if((s.rainStationsAccepted||s.rainStationsRejected)&&rainfallMeta?.available&&!m.getSource('rain-stations')){
      stationsDataUrl.current=`${origin}/api/rainfall/stations?v=${rainfallMeta.revision}`;
      m.addSource('rain-stations',{type:'geojson',data:stationsDataUrl.current,attribution:'Weather Underground stations · supplied QC'});
      m.addLayer({id:'rain-stations-ok',source:'rain-stations',type:'circle',filter:['==',['get','qc'],'ok'],layout:{visibility:s.rainStationsAccepted?'visible':'none'},paint:{'circle-color':'#14b89a','circle-radius':4.5,'circle-stroke-color':'#ecfff4','circle-stroke-width':1.3}},before);
      if(!m.hasImage('rain-rejected-cross')){const width=19,data=new Uint8Array(width*width*4);for(let y=2;y<17;y++)for(let x=2;x<17;x++){const d=Math.min(Math.abs(x-y),Math.abs(x+y-18));if(d<=2){const i=(y*width+x)*4;data.set(d<=1?[239,83,80,255]:[255,239,225,230],i);}}m.addImage('rain-rejected-cross',{width,height:width,data});}
      m.addLayer({id:'rain-stations-rejected',source:'rain-stations',type:'symbol',filter:['!=',['get','qc'],'ok'],layout:{visibility:s.rainStationsRejected?'visible':'none','icon-image':'rain-rejected-cross','icon-size':.85,'icon-allow-overlap':true,'icon-ignore-placement':true}},before);
    }
    ready.current=true;
  }
  useEffect(()=>{
    if(!container.current)return;
    const m=new GLMap({container:container.current,style:styleFor(state,meta),center:[state.lon,state.lat],zoom:state.zoom,bearing:state.bearing,pitch:state.pitch,minZoom:5,maxZoom:21,attributionControl:false,maxPitch:65,canvasContextAttributes:{preserveDrawingBuffer:true}});map.current=m;
    m.addControl(new maplibregl.NavigationControl({showCompass:true}),'top-right');m.addControl(new maplibregl.ScaleControl({unit:'metric'}),'bottom-right');m.addControl(new maplibregl.AttributionControl({compact:true}),'bottom-right');
    m.on('style.load',()=>{ready.current=false;hadError.current=false;setup(m);const c=m.getCenter(),b=m.getBounds();latest.current.onView({lon:c.lng,lat:c.lat,zoom:m.getZoom(),bearing:m.getBearing(),pitch:m.getPitch()},[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]);});
    m.on('moveend',()=>{const c=m.getCenter(),b=m.getBounds();latest.current.onView({lon:c.lng,lat:c.lat,zoom:m.getZoom(),bearing:m.getBearing(),pitch:m.getPitch()},[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]);});
    m.on('click',e=>{const ids=['rain-stations-ok','rain-stations-rejected','route-existing','route-planned','route-open','points','buildings-extrusion','buildings-fill','cadastre-outline','cadastre-fill','history-survey-outline','history-survey-fill','assessment-identifier','assessment-reach','assessment-zone-outline','assessment-zone-fill','green-fill'].filter(id=>m.getLayer(id));const candidates=m.queryRenderedFeatures([[e.point.x-10,e.point.y-10],[e.point.x+10,e.point.y+10]],{layers:ids});const station=candidates.find(f=>f.layer.id.startsWith('rain-stations-'));const f=station||candidates.find(f=>f.layer.id.startsWith('route-'))||candidates[0];const point=station?.geometry.type==='Point'?station.geometry.coordinates:null;latest.current.onInspect(point?Number(point[0]):e.lngLat.lng,point?Number(point[1]):e.lngLat.lat,f);});
    m.on('dataloading',e=>{const source=(e as any).sourceId;if(!hadError.current&&['terrain','pluvial','rainfall'].includes(source))latest.current.onStatus(source==='rainfall'?'Loading daily rainfall…':source==='pluvial'?'Loading 5 m terrain screening…':'Loading terrain…');});
    m.on('idle',()=>{setup(m);if(!hadError.current)latest.current.onStatus(latest.current.state.risk&&(latest.current.state.riskMode==='review'?latest.current.refinementMeta?.available:latest.current.pluvialMeta?.available)?'5 m evidence / terrain screening · 1 m height readout':meta.terrain_available?'1 m terrain connected':'Terrain unavailable');});
    m.on('error',e=>{hadError.current=true;console.error(e.error);const source=(e as any).sourceId;latest.current.onStatus(source==='cadastre-buildings'?'Cadastral building tile request failed':source==='rainfall'?'Rainfall tile request failed':source==='rain-stations'?'Rain-station request failed':source==='flood-assessment'?'Official assessment geometry request failed':source==='history-survey'?'Historical survey geometry request failed':source==='buildings'?'Building context tile request failed':source==='pluvial'?'Pluvial screening tile request failed':source==='terrain'?'Terrain tile request failed':'Map request failed; try another basemap',true);});
    return()=>{marker.current?.remove();marker.current=null;m.remove();map.current=null;};
  },[meta.revision]);
  useEffect(()=>{
    const m=map.current;if(!m)return;
    const key=state.basemap+state.customBasemap;if(key!==lastStyle.current){lastStyle.current=key;ready.current=false;m.setStyle(styleFor(state,meta));}
  },[state.basemap,state.customBasemap]);
  useEffect(()=>{
    const m=map.current;if(!m)return;
    const replaceTiles=(name:string,url:string)=>{const source=m.getSource(name) as any;if(source&&source.tiles?.[0]!==url)source.setTiles([url]);};
    const apply=()=>{if(!ready.current)return;setup(m);
    if(m.getLayer('terrain')){m.setLayoutProperty('terrain','visibility',state.terrain&&state.opacity>0&&scale?'visible':'none');m.setPaintProperty('terrain','raster-opacity',state.opacity);if(scale)replaceTiles('terrain',`${location.origin}/api/raster/${scale.id}/{z}/{x}/{y}.png?v=${meta.revision}&r=${meta.renderer_revision||'v1'}`);}
    if(m.getLayer('hillshade'))m.setLayoutProperty('hillshade','visibility',state.hillshade?'visible':'none');
    if(m.getLayer('rainfall')){m.setLayoutProperty('rainfall','visibility',state.rain&&state.rainOpacity>0&&rainfallMeta?.available?'visible':'none');m.setPaintProperty('rainfall','raster-opacity',state.rainOpacity);if(rainfallMeta?.available)replaceTiles('rainfall',rainfallTileUrl(state,rainfallMeta,meta.renderer_revision||'v1'));}
    if(m.getLayer('rain-stations-ok'))m.setLayoutProperty('rain-stations-ok','visibility',state.rainStationsAccepted&&rainfallMeta?.available?'visible':'none');
    if(m.getLayer('rain-stations-rejected'))m.setLayoutProperty('rain-stations-rejected','visibility',state.rainStationsRejected&&rainfallMeta?.available?'visible':'none');
    if(rainfallMeta?.available){const source=m.getSource('rain-stations') as GeoJSONSource|undefined;const url=`${location.origin}/api/rainfall/stations?v=${rainfallMeta.revision}`;if(source&&stationsDataUrl.current!==url){stationsDataUrl.current=url;source.setData(url);}}
    if(m.getLayer('pluvial')){m.setLayoutProperty('pluvial','visibility',state.risk&&state.riskOpacity>0&&(state.riskMode==='review'?refinementMeta?.available:pluvialMeta?.available)?'visible':'none');m.setPaintProperty('pluvial','raster-opacity',state.riskOpacity);replaceTiles('pluvial',screeningTileUrl(state,pluvialMeta,refinementMeta,meta.renderer_revision||'v1'));}
    ['buildings-fill','buildings-outline'].forEach(id=>{if(m.getLayer(id))m.setLayoutProperty(id,'visibility',state.buildings&&buildingsMeta?.available?'visible':'none');});
    if(m.getLayer('buildings-extrusion'))m.setLayoutProperty('buildings-extrusion','visibility',state.buildings&&state.buildings3d&&buildingsMeta?.available?'visible':'none');
    if(buildingsMeta?.available)replaceTiles('buildings',`${location.origin}/api/buildings/tiles/{z}/{x}/{y}.pbf?v=${buildingsMeta.revision}&r=${meta.renderer_revision||'v1'}`);
    ['cadastre-fill','cadastre-outline'].forEach(id=>{if(m.getLayer(id))m.setLayoutProperty(id,'visibility',state.cadastre&&cadastreMeta?.available?'visible':'none');});
    if(cadastreMeta?.available)replaceTiles('cadastre-buildings',`${location.origin}/api/cadastre/tiles/{z}/{x}/{y}.pbf?v=${cadastreMeta.revision}&r=${meta.renderer_revision||'v1'}`);
    ['history-survey-fill','history-survey-outline'].forEach(id=>{if(m.getLayer(id)){m.setLayoutProperty(id,'visibility',state.historySurvey&&historySurveyMeta?.available?'visible':'none');m.setFilter(id,historyFilter(state));}});
    if(m.getLayer('history-survey-fill'))m.setPaintProperty('history-survey-fill','fill-opacity',state.historyPriority ? .22 : .07);
    if(m.getLayer('history-survey-outline')){m.setPaintProperty('history-survey-outline','line-width',state.historyPriority?3:1.8);m.setPaintProperty('history-survey-outline','line-dasharray',state.historyPriority?null:[3,1.5]);}
    if(historySurveyMeta?.available){const source=m.getSource('history-survey') as GeoJSONSource|undefined;const url=`${location.origin}/api/history/zones.geojson?v=${historySurveyMeta.revision}&r=${meta.renderer_revision||'v1'}`;if(source&&historyDataUrl.current!==url){historyDataUrl.current=url;source.setData(url);}}
    ['assessment-zone-fill','assessment-zone-outline','assessment-reach','assessment-identifier'].forEach(id=>{if(m.getLayer(id))m.setLayoutProperty(id,'visibility',state.assessmentOverlay&&assessmentMeta?.available?'visible':'none');});
    if(assessmentMeta?.available){const source=m.getSource('flood-assessment') as GeoJSONSource|undefined;const url=`${location.origin}/api/flood-assessment/geojson?v=${assessmentMeta.revision}`;if(source&&assessmentDataUrl.current!==url){assessmentDataUrl.current=url;source.setData(url);}}
    ['existing','planned','open'].forEach(status=>{['route-'+status,'route-casing-'+status].forEach(id=>{if(m.getLayer(id))m.setLayoutProperty(id,'visibility',state.statuses.includes(status)?'visible':'none');});});
    replaceTiles('routes',`${location.origin}/api/vector/routes/{z}/{x}/{y}.pbf?v=${meta.revision}&r=${meta.renderer_revision||'v1'}&zone=${state.zone}`);
    ['green-fill','green-outline'].forEach(id=>{if(m.getLayer(id))m.setLayoutProperty(id,'visibility',state.green==='off'?'none':'visible');});
    if(m.getLayer('green-fill'))m.setPaintProperty('green-fill','fill-opacity',state.risk?.06:.19);
    if(m.getLayer('green-outline'))m.setPaintProperty('green-outline','line-opacity',state.risk?.55:.8);
    replaceTiles('green',`${location.origin}/api/vector/green/{z}/{x}/{y}.pbf?v=${meta.revision}&r=${meta.renderer_revision||'v1'}&display=${state.green==='all'?'all':'subset'}`);
    if(m.getLayer('points')){m.setFilter('points',['in',['get','category'],['literal',state.points]]);m.setLayoutProperty('points','visibility',state.points.length?'visible':'none');replaceTiles('points',`${location.origin}/api/vector/points/{z}/{x}/{y}.pbf?v=${meta.revision}&r=${meta.renderer_revision||'v1'}&categories=${state.points.join(',')}`);}};
    if(ready.current)apply();else m.once('style.load',apply);
    return()=>{m.off('style.load',apply);};
  },[state.zone,state.statuses.join(','),state.points.join(','),state.green,state.terrain,state.hillshade,state.opacity,state.risk,state.riskMode,state.riskOpacity,state.buildings,state.buildings3d,state.cadastre,state.historySurvey,state.historyMechanism,state.historyConfidence,state.historyPriority,state.assessmentOverlay,state.rain,state.rainProduct,state.rainOpacity,state.rainSmoothing,state.rainThreshold,state.rainThresholdMm,state.rainStationsAccepted,state.rainStationsRejected,rainfallMeta?.available,rainfallMeta?.revision,buildingZoomVisible,buildingsMeta?.available,buildingsMeta?.revision,cadastreZoomVisible,cadastreMeta?.available,cadastreMeta?.revision,historySurveyMeta?.available,historySurveyMeta?.revision,assessmentMeta?.available,assessmentMeta?.revision,pluvialMeta?.available,pluvialMeta?.revision,refinementMeta?.available,refinementMeta?.revision,scale?.id]);
  useEffect(()=>{
    const m=map.current;if(!m||!focusTarget)return;
    const [west,south,east,north]=focusTarget.bounds;
    m.fitBounds([[west,south],[east,north]],{padding:window.innerWidth<=850?{top:140,bottom:85,left:30,right:60}:{top:135,bottom:80,left:365,right:90},maxZoom:16,bearing:m.getBearing(),pitch:m.getPitch(),duration:window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:800});
  },[focusTarget?.id]);
  useEffect(()=>{
    if(!selected){marker.current?.remove();marker.current=null;return;}
    if(map.current){
      if(!marker.current)marker.current=new Marker({color:'#00d8e8',scale:.75}).setLngLat([selected.lon,selected.lat]).addTo(map.current);
      else marker.current.setLngLat([selected.lon,selected.lat]);
    }
  },[selected]);
  return <div className="map" ref={container} aria-label="Interactive Sofia terrain and sewer map"/>;
}




