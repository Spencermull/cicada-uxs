#pragma once
#include <chrono>
#include <mutex>
#include <stdexcept>
#include <string>

using timestamp_t = std::chrono::steady_clock::time_point;
using radians_t = float;
struct VehicleStates
{
    double positionX;
    double positionY;
    int32_t lat;
    int32_t lon;
    int32_t alt;
    int32_t relative_alt;
    uint16_t hdg;
    radians_t roll;
    radians_t pitch;
    radians_t yaw;

    uint16_t voltage;
    uint16_t current;
    int8_t remainingBattery;

    bool armed;
    bool gpsFixed;
    std::string flightMode;

    timestamp_t lastHeartBeat;
    std::mutex mtx;
};
