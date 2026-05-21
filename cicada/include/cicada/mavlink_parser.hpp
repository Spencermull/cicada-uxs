#pragma once
#include <ardupilotmega/mavlink.h>
#include <winsock2.h> // windows specific networking libs
#include <ws2tcpip.h>
#include <stdexcept>
#pragma comment(lib, "ws2_32.lib") // TODO migrate to fit with gcc toolchain

class UdpSocket // UDP socket opener class
{
private:
    SOCKET sock;
    sockaddr_in localAddr;
    WSADATA wsaData;

public:
    UdpSocket()
    {

        int result = WSAStartup(MAKEWORD(2, 2), &wsaData); // check if process is up
        if (result != 0)
        {
            throw std::runtime_error("WSAStartup Failed");
        }

        sock = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP); // define the win socket for udp (IPv4)
        if (sock == INVALID_SOCKET)
        {
            throw std::runtime_error("socket failed");
        }
        localAddr.sin_family = AF_INET;
        localAddr.sin_port = htons(14550);      // mavsdk's default port
        localAddr.sin_addr.s_addr = INADDR_ANY; // allows packets from any network interface on this ip
        if (bind(sock, (sockaddr *)&localAddr, sizeof(localAddr)) == SOCKET_ERROR)
        {
            throw std::runtime_error("Bind failed");
        };
    }

    int receive(uint8_t *buffer, int bufferSize) // recieves raw bytes
    {                                                                                
        int bytes = recvfrom(sock, (char *)buffer, bufferSize, 0, nullptr, nullptr); // uses nullptr as we assume all packets come from the SITL
        if (bytes == SOCKET_ERROR)
        {
            throw std::runtime_error("recvfrom failed");
        }
        return bytes; // returns raw bytes from SITL traffic
    };

    // destruct socket
    ~UdpSocket()
    {
        closesocket(sock);
        WSACleanup();
    }
};

class MavLinkParser
{
    mavlink_message_t msg;
    mavlink_status_t status;
    uint8_t buffer[2048]; // update to fit mavsdk frame output
public:
    // TODO: Parser constructor and parse method
};
