#include <cassert>
#include <cmath>
#include <iostream>
#include "Mileage.h"
bool close(double a,double b) { return std::abs(a-b)<1e-9; }
int main() {
 Mileage m;
 m.reset(); m.sample(1000,100,true);
 assert(close(m.sample(2000,100,true),100.0/3600*0.621371192237334));
 double saved=m.total;
 m.sample(3000,-1,false); m.sample(4000,100,true);
 assert(close(m.total,saved)); assert(m.missedMs==2000);
 m.sample(15000,100,true); assert(close(m.total,saved)); assert(m.missedMs==13000);
 m.sample(16000,300,true); m.sample(17000,0,true);
 assert(close(m.total,saved));
 m.reset(); m.sample(0,0,true); m.sample(1000,100,true);
 assert(close(m.total,50.0/3600*0.621371192237334));
 m.reset(1.1); m.sample(0,100,true); m.sample(1000,100,true);
 assert(close(m.total,110.0/3600*0.621371192237334));
 m.reset(); m.sample(4294967290ULL,100,true); m.sample(4294968290ULL,100,true);
 assert(close(m.total,100.0/3600*0.621371192237334));
 std::cout << "Mileage: steady speed, acceleration, missing data, long gap, invalid speed, calibration, 32-bit rollover passed\n";
}
