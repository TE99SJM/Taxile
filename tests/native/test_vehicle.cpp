#include <cassert>
#include <cstdio>
#include <string>
#include "../../firmware/Taxile/Vehicle.h"
const char* A="1M8GDM9AXKP042788";
const char* B="1HGCM82633A004352";
std::string reply(const char* vin) {
 std::string out="014\r0: 49 02 01";
 for(int i=0;i<17;++i) {
  if(i==3) out+="\r1:";
  if(i==10) out+="\r2:";
  char h[4]; snprintf(h,sizeof(h)," %02X",(unsigned char)vin[i]); out+=h;
 }
 return out+"\r>";
}
int main() {
 char vin[18];
 assert(parseVIN(reply(A).c_str(),vin) && !strcmp(vin,A));
 assert(parseVIN(reply(B).c_str(),vin) && !strcmp(vin,B));
 std::string legacy;
 for(int start=0,n=1;start<17;start+=4,++n) {
  char header[16]; snprintf(header,sizeof(header),"49 02 %02X",n);legacy+=header;
  for(int i=start;i<start+4 && i<17;++i) { char h[4];snprintf(h,sizeof(h)," %02X",A[i]);legacy+=h; }
  legacy+='\r';
 }
 assert(parseVIN(legacy.c_str(),vin) && !strcmp(vin,A));
 assert(!parseVIN((reply(A)+reply(B)).c_str(),vin));
 for(auto bad:{"", "NO DATA", "49 02 01 31 32 33\r>","49 02 01 49 4F 51\r>"}) assert(!parseVIN(bad,vin));
 assert(!validVIN("00000000000000000"));
 VehicleIdentity device;
 assert(device.identify(reply(A).c_str()));device.startTrip();assert(!strcmp(device.recordedVIN(),A));
 device.resetConnection();assert(!device.current[0]);assert(!strcmp(device.recordedVIN(),A));
 assert(!device.identify("NO DATA"));device.startTrip();assert(!device.recordedVIN()[0]);
 assert(device.identify(reply(B).c_str()));assert(!device.recordedVIN()[0]); // unknown history stays unknown
 device.startTrip();assert(!strcmp(device.recordedVIN(),B));
 assert(!device.identify((reply(A)+reply(B)).c_str()));assert(!device.current[0]);
 puts("VIN parsing and vehicle swap tests passed");
}
