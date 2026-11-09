// Test the production parser without ESP32 hardware or Arduino runtime.
#include <vector>
#include <string>
#include <cstring>
#include <cstdio>
#include <cassert>
using String=std::string;
struct JsonVariant {
 std::string value;
 template<class T> T as() const { return value; }
};
struct JsonArray {
 std::vector<JsonVariant>* data;
 auto begin() { return data->begin(); } auto end() { return data->end(); }
 void add(const char* v) { data->push_back({v}); }
};
struct JsonDocument {
 std::vector<JsonVariant> codes;
 JsonArray createNestedArray(const char*) { codes.clear(); return {&codes}; }
 bool overflowed() const { return false; }
};
#include "../../firmware/Taxile/Diagnostics.h"
int main() {
 JsonDocument d;
 assert(parseDiagnostic("43 01 33 03 01 00 00\r>",false,d));
 assert(d.codes.size()==2 && d.codes[0].value=="P0133" && d.codes[1].value=="P0301");
 assert(parseDiagnostic("0: 43 04 01 08 01 09\r1: 01 01 11 01 15 00 00\r>",false,d));
 assert(d.codes.size()==5 && d.codes[4].value=="P0115");
 assert(parseDiagnostic("43 43 01 83 02 C1 23\r>",false,d));
 assert(d.codes[0].value=="C0301" && d.codes[1].value=="B0302" && d.codes[2].value=="U0123");
 assert(parseDiagnostic("43 01 33 00 00\r43 01 33 03 01\r>",false,d) && d.codes.size()==2);
 assert(parseDiagnostic("43 00 00 00 00 00 00\r>",false,d) && d.codes.empty());
 assert(parseDiagnostic("44\r>",true,d));
 for(auto input:{"NO DATA\r>","", "STOPPED", "43 01\r>","43 01 33\rBUFFER FULL\r>","43 01 ZZ\r>"}) assert(!parseDiagnostic(input,false,d));
 assert(!parseDiagnostic("OK\r>",true,d));
 assert(!parseDiagnostic("43 00 00\r>",true,d));
 assert(parseDiagnostic("43 02 01 33 03 01 00\r>",false,d,true) && d.codes.size()==2);
 assert(parseDiagnostic("43 00 00 00 00 00 00\r>",false,d,true) && d.codes.empty());
 assert(!parseDiagnostic("43 02 01 33\r>",false,d,true));
 assert(parseDiagnostic("0: 43 04 01 08 01 09\r1: 01 11 01 15 00 00 00\r>",false,d,true));
 assert(d.codes.size()==4 && d.codes[0].value=="P0108" && d.codes[3].value=="P0115");
 assert(diagnosticProtocol("A6\r>")==6 && diagnosticProtocol("3\r>")==3 && diagnosticProtocol("ERROR\r>")==-1);
 puts("Diagnostic response parser tests passed");
}
