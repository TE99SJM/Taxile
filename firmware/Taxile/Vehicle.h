#pragma once
#include <ctype.h>
#include <string.h>
#include <stdlib.h>

inline bool validVIN(const char* vin) {
 if(strlen(vin)!=17) return false;
 bool varied=false;
 for(int i=0;i<17;++i) {
  char c=vin[i];
  if(!((c>='A' && c<='Z' && c!='I' && c!='O' && c!='Q') || (c>='0' && c<='9'))) return false;
  if(c!=vin[0]) varied=true;
 }
 return varied;
}
// Header-free Mode 09 PID 02: CAN numbered continuations and legacy numbered
// records. Accept one consistent, complete 17-character VIN; never guess.
inline bool parseVIN(const char* input,char out[18]) {
 out[0]=0;
 if(strstr(input,"NO DATA") || strstr(input,"ERROR") || strstr(input,"UNABLE") || strstr(input,"STOPPED")) return false;
 char candidate[18]={0}; int size=0; bool collecting=false, found=false;
 const char* p=input;
 while(*p) {
  const char* end=p; while(*end && *end!='\r' && *end!='\n' && *end!='>') ++end;
  const char* colon=nullptr; for(const char* q=p;q<end;++q) if(*q==':') colon=q;
  unsigned char bytes[128]; int count=0;
  for(const char* q=colon?colon+1:p;q<end;) {
   while(q<end && isspace((unsigned char)*q)) ++q;
   const char* token=q; while(q<end && !isspace((unsigned char)*q)) ++q;
   if(q-token==2 && isxdigit((unsigned char)token[0]) && isxdigit((unsigned char)token[1])) {
    if(count==128) return false;
    char h[3]={token[0],token[1],0}; bytes[count++]=strtol(h,nullptr,16);
   }
  }
  int begin=0;
  if(count>=3 && bytes[0]==0x49 && bytes[1]==0x02) {
   if(bytes[2]==1) {
    if(collecting && size!=17) return false;
    size=0; candidate[0]=0;
   } else if(!collecting || size==17) return false;
   collecting=true; begin=3;
  }
  if(collecting) {
   for(int i=begin;i<count;++i) {
    if(bytes[i]==0 && (size==0 || size==17)) continue;
    if(size==17) return false;
    candidate[size++]=bytes[i]; candidate[size]=0;
   }
   if(size==17) {
    if(!validVIN(candidate) || (found && strcmp(out,candidate))) { out[0]=0; return false; }
    strcpy(out,candidate); found=true;
   }
  }
  p=end; while(*p=='\r' || *p=='\n' || *p=='>') ++p;
 }
 if(!found || size!=17) { out[0]=0; return false; }
 return true;
}

struct VehicleIdentity {
 char current[18]={0}, tripVIN[18]={0};
 void resetConnection() { current[0]=0; }
 bool identify(const char* response) { if(parseVIN(response,current)) return true; current[0]=0; return false; }
 void startTrip() { strcpy(tripVIN,current); }
 // Never relabel an unknown trip if VIN becomes available later.
 const char* recordedVIN() const { return tripVIN; }
};
