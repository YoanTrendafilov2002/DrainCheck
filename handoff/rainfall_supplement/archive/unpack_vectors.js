// Lossless DEFLATE decoder for the embedded GeoJSON coordinate payload.
// All original coordinate digits and attributes are retained.
exports.unpack = function(first) {
  var text = first + PACKED_REST;
  var alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  var input = [], acc = 0, bits = 0, i;
  for(i=0;i<text.length;i++) {
    var v=alphabet.indexOf(text.charAt(i));
    if(v<0)continue;
    acc=(acc<<6)|v;bits+=6;
    if(bits>=8){bits-=8;input.push((acc>>>bits)&255);}
  }
  var pos=0, bitbuf=0, bitcount=0, output=[];
  function read(n) {
    while(bitcount<n){if(pos>=input.length)throw new Error('Truncated vector data');bitbuf|=input[pos++]<<bitcount;bitcount+=8;}
    var value=bitbuf&((1<<n)-1);bitbuf>>>=n;bitcount-=n;return value;
  }
  function tree(lengths) {
    var counts=[],next=[],tables=[],code=0,k,j;
    for(k=0;k<=15;k++){counts[k]=0;tables[k]={};}
    for(k=0;k<lengths.length;k++)counts[lengths[k]]++;
    counts[0]=0;
    for(k=1;k<=15;k++){code=(code+counts[k-1])*2;next[k]=code;}
    for(k=0;k<lengths.length;k++) {
      var len=lengths[k];if(!len)continue;
      var c=next[len]++,reverse=0;
      for(j=0;j<len;j++){reverse=reverse*2+(c&1);c>>>=1;}
      tables[len][reverse]=k;
    }
    return tables;
  }
  function symbol(t) {
    var code=0;
    for(var len=1;len<=15;len++) {
      code|=read(1)<<(len-1);
      if(t[len][code]!==undefined)return t[len][code];
    }
    throw new Error('Invalid vector compression');
  }
  var lengthBase=[3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258];
  var lengthExtra=[0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0];
  var distBase=[1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577];
  var distExtra=[0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13];
  var done=false;
  while(!done) {
    done=read(1)===1;var type=read(2),lit,dist,lens=[],k;
    if(type===0) {
      bitbuf=0;bitcount=0;var n=read(16),complement=read(16);
      if((n^65535)!==complement)throw new Error('Invalid stored block');
      for(k=0;k<n;k++)output.push(read(8));continue;
    }
    if(type===1) {
      for(k=0;k<288;k++)lens.push(k<144?8:k<256?9:k<280?7:8);
      lit=tree(lens);lens=[];for(k=0;k<32;k++)lens.push(5);dist=tree(lens);
    } else if(type===2) {
      var nl=read(5)+257,nd=read(5)+1,nc=read(4)+4;
      var order=[16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15];
      var cl=[];for(k=0;k<19;k++)cl.push(0);
      for(k=0;k<nc;k++)cl[order[k]]=read(3);
      var ct=tree(cl);
      while(lens.length<nl+nd) {
        var s=symbol(ct),repeat,value;
        if(s<16)lens.push(s);
        else {
          if(s===16){repeat=read(2)+3;value=lens[lens.length-1];}
          else if(s===17){repeat=read(3)+3;value=0;}
          else{repeat=read(7)+11;value=0;}
          while(repeat--)lens.push(value);
        }
      }
      lit=tree(lens.slice(0,nl));dist=tree(lens.slice(nl));
    } else throw new Error('Reserved vector compression block');
    while(true) {
      var item=symbol(lit);
      if(item<256){output.push(item);continue;}
      if(item===256)break;
      var lidx=item-257,len=lengthBase[lidx]+read(lengthExtra[lidx]);
      var didx=symbol(dist),distance=distBase[didx]+read(distExtra[didx]);
      for(k=0;k<len;k++)output.push(output[output.length-distance]);
    }
  }
  var chars=[];
  for(i=0;i<output.length;i++)chars.push(String.fromCharCode(output[i]));
  return JSON.parse(chars.join(''));
};
