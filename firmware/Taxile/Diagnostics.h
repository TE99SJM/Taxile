#pragma once
#include <ctype.h>
#include <stdlib.h>
// Header-free ELM responses. Numbered continuation lines are joined; separate
// ECU replies start a new 43 payload. Reject truncated/ambiguous hex data.
inline bool parseDiagnostic(const char* input,bool clear,JsonDocument& doc,bool can=false) {
 if(strstr(input,"NO DATA") || strstr(input,"ERROR") || strstr(input,"UNABLE") || strstr(input,"TIMEOUT") || strstr(input,"BUFFER FULL") || strstr(input,"STOPPED")) return false;
 JsonArray codes=doc.createNestedArray("codes");
 bool found=false, payload=false, needCount=false; int high=-1, remaining=-1; bool malformed=false;
 const char* p=input;
 while(*p) {
  const char* end=p; while(*end && *end!='\r' && *end!='\n' && *end!='>') ++end;
  const char* colon=nullptr; for(const char* q=p;q<end;++q) if(*q==':') colon=q;
  const char* q=colon?colon+1:p;
  while(q<end) {
   while(q<end && isspace((unsigned char)*q)) ++q;
   if(q==end) break;
   const char* token=q; while(q<end && !isspace((unsigned char)*q)) ++q;
   if(q-token!=2 || !isxdigit(token[0]) || !isxdigit(token[1])) { if(payload) malformed=true; continue; }
   char hex[3]={token[0],token[1],0}; int b=strtol(hex,nullptr,16);
   // Positive service byte only at the beginning of a reply line.
   bool first=true; for(const char* t=colon?colon+1:p;t<token;++t) if(!isspace((unsigned char)*t)) first=false;
   if(first && (!colon || strtol(p,nullptr,16)==0) && b==(clear?0x44:0x43)) { if(high>0) malformed=true; if(remaining>0) malformed=true; found=true; payload=true; high=-1; needCount=can && !clear; remaining=-1; continue; }
   if(clear || !payload) continue;
   if(needCount) { remaining=b; needCount=false; continue; }
   if(can && remaining==0) continue;
   if(high<0) high=b;
   else { unsigned code=(high<<8)|b; high=-1; if(can && remaining>0) --remaining;
    if(code) { char formatted[6]; snprintf(formatted,sizeof(formatted),"%c%04X","PCBU"[(code>>14)&3],code&0x3fff);
     bool duplicate=false; for(JsonVariant v:codes) if(v.as<String>()==formatted) duplicate=true;
     if(!duplicate) codes.add(formatted);
    }
   }
  }
  if(!colon) { if(high>0) malformed=true; payload=false; high=-1; }
  p=end; while(*p=='\r' || *p=='\n' || *p=='>') ++p;
 }
 // A final zero is valid padding; a nonzero orphan is incomplete.
 if(high>0 || remaining>0 || needCount) malformed=true;
 return found && !malformed && !doc.overflowed();
}

inline int diagnosticProtocol(const char* input) {
 const char* p=input;
 while(*p) {
  while(*p && isspace((unsigned char)*p)) ++p;
  const char* end=p; while(*end && !isspace((unsigned char)*end) && *end!='>') ++end;
  int size=end-p;
  if(size==2 && (*p=='A' || *p=='a')) { ++p; --size; }
  if(size==1 && isxdigit((unsigned char)*p)) { char b[2]={*p,0}; int n=strtol(b,nullptr,16); if(n>=1 && n<=12) return n; }
  if(!*end) break;
  p=end+1;
 }
 return -1;
}
