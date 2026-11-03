#pragma once

#include <string>

class RTWindow;

bool testLiveParamShutdown(RTWindow *, const std::string &);
bool testLiveParamJson(RTWindow *, const std::string &);
bool testLiveParamTypes(RTWindow *, const std::string &);
bool testLiveParamFrames(RTWindow *, const std::string &);
bool testLiveParamQueue(RTWindow *, const std::string &);
bool testLiveParamStartup(RTWindow *, const std::string &);
