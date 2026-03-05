//+------------------------------------------------------------------+
//| QuantFundBridge.mq5                                              |
//| Bridges the Rust QuantFund engine <-> MetaTrader 5 terminal      |
//|                                                                  |
//| ## Overview                                                      |
//| This EA acts as the TCP server on port 9090 (configurable).      |
//| The Rust engine connects as a client and sends newline-delimited |
//| JSON commands; this EA executes them via CTrade and reports      |
//| fills, rejections, and account updates back over the same        |
//| connection.                                                      |
//|                                                                  |
//| ## Message format                                                |
//| Every message is a single JSON line terminated by \n.            |
//|                                                                  |
//| ## Inbound (Rust -> MT5)                                         |
//|   {"type":"new_order", ...Mt5OrderRequest fields...}             |
//|   {"type":"modify_order", "order_id":"...", "new_sl":"...", ...} |
//|   {"type":"cancel_order", "order_id":"..."}                      |
//|   {"type":"close_position", "order_id":"..."}                    |
//|   {"type":"ping", "seq":42}                                      |
//|                                                                  |
//| ## Outbound (MT5 -> Rust)                                        |
//|   {"type":"ack", "order_id":"...", "mt5_ticket":..., ...}        |
//|   {"type":"fill", "order_id":"...", ...}                         |
//|   {"type":"partial_fill", ...}                                   |
//|   {"type":"rejection", "order_id":"...", "retcode":..., ...}     |
//|   {"type":"tick", "symbol":"...", "bid":"...", ...}              |
//|   {"type":"account_update", "balance":"...", ...}                |
//|   {"type":"pong", "seq":42}                                      |
//|                                                                  |
//| ## Prerequisites                                                 |
//| Tools -> Options -> Expert Advisors -> Allow algorithmic trading |
//| The EA uses MQL5 socket functions (MT5 build 2540+).            |
//+------------------------------------------------------------------+
#property copyright "QuantFund"
#property link      "https://github.com/QuantFund/engine"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//--- Input parameters
input int    BridgePort         = 9090;     // TCP listen port
input bool   ForwardTicks       = true;     // Push tick data to Rust engine
input bool   ForwardAccountInfo = true;     // Push account updates periodically
input int    AccountUpdateSec   = 30;       // Seconds between account updates
input int    MaxConnectRetries  = 3;        // Max reconnect attempts
input bool   DebugWire          = false;    // Log every raw message (verbose)

//--- Global state
int      g_serverSocket   = INVALID_HANDLE;
int      g_clientSocket   = INVALID_HANDLE;
bool     g_connected      = false;
datetime g_lastAccountUpd = 0;
long     g_lastDealTicket = 0;  // Highest processed deal ticket for dedup.

CTrade          g_trade;
CPositionInfo   g_pos;
COrderInfo      g_ord;

// Map from Rust OrderId (string) -> MT5 ticket assigned after OrderSend.
// Stored so we can close positions by Rust ID.
// MQL5 has no std::map; we use parallel arrays (max 512 concurrent orders).
#define MAX_ORDERS 512
string   g_rustIds[MAX_ORDERS];
ulong    g_mt5Tickets[MAX_ORDERS];
int      g_mapSize = 0;

//+------------------------------------------------------------------+
//| Expert initialisation                                            |
//+------------------------------------------------------------------+
int OnInit()
{
    Print("QuantFundBridge: initialising on port ", BridgePort);

    g_trade.SetExpertMagicNumber(20250304);
    g_trade.SetDeviationInPoints(20);
    g_trade.SetTypeFilling(ORDER_FILLING_IOC);
    g_trade.LogLevel(LOG_LEVEL_NO); // Suppress CTrade's own print spam.

    if (!StartServer())
    {
        Print("QuantFundBridge: failed to start server");
        return INIT_FAILED;
    }

    EventSetTimer(1); // 1-second timer for account updates and keepalive.
    Print("QuantFundBridge: ready, waiting for Rust engine connection...");
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    StopServer();
    Print("QuantFundBridge: deinitialised");
}

//+------------------------------------------------------------------+
//| OnTick — forward tick data and drain inbound command buffer      |
//+------------------------------------------------------------------+
void OnTick()
{
    // Accept new client connection if none is active.
    if (!g_connected)
        TryAcceptClient();

    if (!g_connected)
        return;

    // Forward tick to Rust engine if enabled.
    if (ForwardTicks)
        SendTick();

    // Drain inbound command lines.
    ProcessInbound();

    // Check for new deal history (fills).
    CheckNewDeals();
}

//+------------------------------------------------------------------+
//| Timer — periodic account updates                                 |
//+------------------------------------------------------------------+
void OnTimer()
{
    if (!g_connected)
    {
        TryAcceptClient();
        return;
    }

    if (ForwardAccountInfo)
    {
        datetime now = TimeCurrent();
        if (now - g_lastAccountUpd >= AccountUpdateSec)
        {
            SendAccountUpdate();
            g_lastAccountUpd = now;
        }
    }
}

//+------------------------------------------------------------------+
//| Server lifecycle                                                 |
//+------------------------------------------------------------------+
bool StartServer()
{
    g_serverSocket = SocketCreate();
    if (g_serverSocket == INVALID_HANDLE)
    {
        Print("SocketCreate failed: ", GetLastError());
        return false;
    }

    if (!SocketBind(g_serverSocket, "", BridgePort))
    {
        Print("SocketBind failed on port ", BridgePort, ": ", GetLastError());
        SocketClose(g_serverSocket);
        g_serverSocket = INVALID_HANDLE;
        return false;
    }

    if (!SocketListen(g_serverSocket, 1))
    {
        Print("SocketListen failed: ", GetLastError());
        SocketClose(g_serverSocket);
        g_serverSocket = INVALID_HANDLE;
        return false;
    }

    Print("QuantFundBridge: listening on port ", BridgePort);
    return true;
}

void StopServer()
{
    if (g_clientSocket != INVALID_HANDLE)
    {
        SocketClose(g_clientSocket);
        g_clientSocket = INVALID_HANDLE;
        g_connected = false;
    }
    if (g_serverSocket != INVALID_HANDLE)
    {
        SocketClose(g_serverSocket);
        g_serverSocket = INVALID_HANDLE;
    }
}

void TryAcceptClient()
{
    if (g_serverSocket == INVALID_HANDLE)
        return;

    // Non-blocking accept.
    string clientAddr;
    uint   clientPort;
    int    client = SocketAccept(g_serverSocket, clientAddr, clientPort);
    if (client == INVALID_HANDLE)
        return; // No pending connection.

    // If there was an old client, close it first.
    if (g_clientSocket != INVALID_HANDLE)
        SocketClose(g_clientSocket);

    g_clientSocket = client;
    g_connected    = true;

    Print("QuantFundBridge: Rust engine connected from ", clientAddr, ":", clientPort);
    SendAccountUpdate(); // Send initial state.
    g_lastAccountUpd = TimeCurrent();
}

//+------------------------------------------------------------------+
//| Inbound message processing                                       |
//+------------------------------------------------------------------+
void ProcessInbound()
{
    if (!g_connected) return;

    // Read until no more complete lines are available.
    while (true)
    {
        string line = ReadLine();
        if (line == "") break;

        if (DebugWire)
            Print("WIRE IN: ", line);

        DispatchMessage(line);
    }
}

/// Read one newline-terminated line from the client socket.
/// Returns "" if no complete line is available yet.
string ReadLine()
{
    static string g_buf = "";

    // Try to append available bytes.
    uint available = SocketIsReadable(g_clientSocket);
    if (available > 0)
    {
        uchar raw[];
        int received = SocketRead(g_clientSocket, raw, (int)MathMin(available, 4096), 0);
        if (received > 0)
        {
            g_buf += CharArrayToString(raw, 0, received);
        }
        else if (received < 0)
        {
            // Connection dropped.
            Print("QuantFundBridge: client disconnected (read error)");
            SocketClose(g_clientSocket);
            g_clientSocket = INVALID_HANDLE;
            g_connected    = false;
            g_buf = "";
            return "";
        }
    }

    // Extract one complete line.
    int nl = StringFind(g_buf, "\n");
    if (nl < 0) return ""; // Incomplete line, wait for more data.

    string line = StringSubstr(g_buf, 0, nl);
    g_buf = StringSubstr(g_buf, nl + 1);
    return line;
}

//+------------------------------------------------------------------+
//| Message dispatcher                                               |
//+------------------------------------------------------------------+
void DispatchMessage(const string &line)
{
    string msgType = JsonGetString(line, "type");

    if (msgType == "new_order")
        HandleNewOrder(line);
    else if (msgType == "modify_order")
        HandleModifyOrder(line);
    else if (msgType == "cancel_order")
        HandleCancelOrder(line);
    else if (msgType == "close_position")
        HandleClosePosition(line);
    else if (msgType == "ping")
    {
        string seq = JsonGetString(line, "seq");
        SendLine("{\"type\":\"pong\",\"seq\":" + seq + "}");
    }
    else
    {
        Print("QuantFundBridge: unknown message type '", msgType, "'");
        SendLine("{\"type\":\"error\",\"message\":\"unknown message type: " + msgType + "\"}");
    }
}

//+------------------------------------------------------------------+
//| Order handlers                                                   |
//+------------------------------------------------------------------+
void HandleNewOrder(const string &line)
{
    string orderId   = JsonGetString(line, "order_id");
    string symbol    = JsonGetString(line, "symbol");
    string action    = JsonGetString(line, "action");
    string orderType = JsonGetString(line, "order_type");
    double volume    = StringToDouble(JsonGetString(line, "volume"));
    double price     = StringToDouble(JsonGetString(line, "price"));
    double sl        = StringToDouble(JsonGetString(line, "sl"));
    double tp        = StringToDouble(JsonGetString(line, "tp"));
    long   magic     = StringToInteger(JsonGetString(line, "magic"));
    string comment   = JsonGetString(line, "comment");

    // Clamp comment to 31 chars (MT5 limit).
    if (StringLen(comment) > 31)
        comment = StringSubstr(comment, 0, 31);

    g_trade.SetExpertMagicNumber(magic > 0 ? magic : 20250304);

    bool ok = false;

    if (orderType == "market")
    {
        if (action == "buy")
            ok = g_trade.Buy(volume, symbol, 0, sl > 0 ? sl : 0, tp > 0 ? tp : 0, comment);
        else
            ok = g_trade.Sell(volume, symbol, 0, sl > 0 ? sl : 0, tp > 0 ? tp : 0, comment);
    }
    else if (orderType == "limit")
    {
        ENUM_ORDER_TYPE type = (action == "buy") ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
        ok = g_trade.OrderOpen(symbol, type, volume, 0, price, sl > 0 ? sl : 0, tp > 0 ? tp : 0, ORDER_TIME_GTC, 0, comment);
    }
    else if (orderType == "stop")
    {
        ENUM_ORDER_TYPE type = (action == "buy") ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
        ok = g_trade.OrderOpen(symbol, type, volume, 0, price, sl > 0 ? sl : 0, tp > 0 ? tp : 0, ORDER_TIME_GTC, 0, comment);
    }
    else if (orderType == "stop_limit")
    {
        ENUM_ORDER_TYPE type = (action == "buy") ? ORDER_TYPE_BUY_STOP_LIMIT : ORDER_TYPE_SELL_STOP_LIMIT;
        double stopPrice = StringToDouble(JsonGetString(line, "stop_price"));
        ok = g_trade.OrderOpen(symbol, type, volume, stopPrice, price, sl > 0 ? sl : 0, tp > 0 ? tp : 0, ORDER_TIME_GTC, 0, comment);
    }

    if (ok)
    {
        ulong ticket = g_trade.ResultOrder();
        MapSet(orderId, ticket);

        string ack = "{\"type\":\"ack\","
                   + "\"order_id\":\"" + orderId + "\","
                   + "\"mt5_ticket\":" + IntegerToString(ticket) + ","
                   + "\"timestamp_ms\":" + IntegerToString(GetCurrentTimeMs())
                   + "}";
        SendLine(ack);

        if (DebugWire)
            Print("QuantFundBridge: new_order OK ticket=", ticket, " order_id=", orderId);
    }
    else
    {
        int    retcode = (int)g_trade.ResultRetcode();
        string msg     = g_trade.ResultRetcodeDescription();

        // Escape double-quotes in msg.
        StringReplace(msg, "\"", "'");

        string rej = "{\"type\":\"rejection\","
                   + "\"order_id\":\"" + orderId + "\","
                   + "\"retcode\":" + IntegerToString(retcode) + ","
                   + "\"message\":\"" + msg + "\""
                   + "}";
        SendLine(rej);

        Print("QuantFundBridge: new_order REJECTED retcode=", retcode, " ", msg);
    }
}

void HandleModifyOrder(const string &line)
{
    string orderId = JsonGetString(line, "order_id");
    double newSl   = StringToDouble(JsonGetString(line, "new_sl"));
    double newTp   = StringToDouble(JsonGetString(line, "new_tp"));

    // Try as open position first.
    ulong ticket = MapGet(orderId);
    bool  ok     = false;

    if (ticket > 0 && g_pos.SelectByTicket(ticket))
    {
        ok = g_trade.PositionModify(ticket, newSl > 0 ? newSl : g_pos.StopLoss(), newTp > 0 ? newTp : g_pos.TakeProfit());
    }
    else if (ticket > 0)
    {
        // Try pending order.
        if (g_ord.Select(ticket))
            ok = g_trade.OrderModify(ticket, g_ord.PriceOpen(), newSl > 0 ? newSl : g_ord.StopLoss(), newTp > 0 ? newTp : g_ord.TakeProfit(), g_ord.TypeTime(), g_ord.TimeExpiration());
    }

    if (!ok)
        Print("QuantFundBridge: modify_order failed for order_id=", orderId);
}

void HandleCancelOrder(const string &line)
{
    string orderId = JsonGetString(line, "order_id");
    ulong  ticket  = MapGet(orderId);

    if (ticket == 0)
    {
        Print("QuantFundBridge: cancel_order — no MT5 ticket for order_id=", orderId);
        return;
    }

    bool ok = g_trade.OrderDelete(ticket);
    if (ok)
    {
        string cancelled = "{\"type\":\"cancelled\","
                         + "\"order_id\":\"" + orderId + "\","
                         + "\"mt5_ticket\":" + IntegerToString(ticket) + ","
                         + "\"timestamp_ms\":" + IntegerToString(GetCurrentTimeMs())
                         + "}";
        SendLine(cancelled);
        MapRemove(orderId);
    }
    else
    {
        Print("QuantFundBridge: cancel_order FAILED ticket=", ticket, " retcode=", g_trade.ResultRetcode());
    }
}

void HandleClosePosition(const string &line)
{
    string orderId = JsonGetString(line, "order_id");
    ulong  ticket  = MapGet(orderId);

    if (ticket == 0)
    {
        Print("QuantFundBridge: close_position — no MT5 ticket for order_id=", orderId);
        return;
    }

    string volStr = JsonGetString(line, "volume");
    bool   ok;

    if (volStr == "" || volStr == "null")
    {
        ok = g_trade.PositionClose(ticket);
    }
    else
    {
        double vol = StringToDouble(volStr);
        ok = g_trade.PositionClosePartial(ticket, vol);
    }

    if (!ok)
        Print("QuantFundBridge: close_position FAILED ticket=", ticket, " retcode=", g_trade.ResultRetcode());
}

//+------------------------------------------------------------------+
//| Deal monitoring — send fill events when new deals arrive         |
//+------------------------------------------------------------------+
void CheckNewDeals()
{
    HistorySelect(TimeCurrent() - 300, TimeCurrent() + 1); // Last 5 minutes.
    int total = HistoryDealsTotal();

    for (int i = total - 1; i >= 0; i--)
    {
        ulong ticket = HistoryDealGetTicket(i);
        if (ticket == 0) continue;
        if ((long)ticket <= g_lastDealTicket) break; // Already processed.

        ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY);
        if (entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT)
            continue;

        long   orderTicket = HistoryDealGetInteger(ticket, DEAL_ORDER);
        long   posTicket   = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
        string symbol      = HistoryDealGetString(ticket, DEAL_SYMBOL);
        double volume      = HistoryDealGetDouble(ticket, DEAL_VOLUME);
        double price       = HistoryDealGetDouble(ticket, DEAL_PRICE);
        double commission  = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
        double swap        = HistoryDealGetDouble(ticket, DEAL_SWAP);
        long   timeMs      = HistoryDealGetInteger(ticket, DEAL_TIME_MSC);

        ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
        string action = (dealType == DEAL_TYPE_BUY) ? "buy" : "sell";

        // Reverse-look up the Rust order_id from the MT5 order ticket.
        string rustId = MapGetByTicket((ulong)orderTicket);
        if (rustId == "") rustId = "unknown"; // Deal from manual trade or another EA.

        string fill = "{\"type\":\"fill\","
                    + "\"order_id\":\"" + rustId + "\","
                    + "\"deal_ticket\":" + IntegerToString(ticket) + ","
                    + "\"position_ticket\":" + IntegerToString(posTicket) + ","
                    + "\"symbol\":\"" + symbol + "\","
                    + "\"action\":\"" + action + "\","
                    + "\"volume\":\"" + DoubleToString(volume, 2) + "\","
                    + "\"fill_price\":\"" + DoubleToString(price, 5) + "\","
                    + "\"commission\":\"" + DoubleToString(commission, 2) + "\","
                    + "\"swap\":\"" + DoubleToString(swap, 2) + "\","
                    + "\"timestamp_ms\":" + IntegerToString(timeMs)
                    + "}";

        SendLine(fill);

        if ((long)ticket > g_lastDealTicket)
            g_lastDealTicket = (long)ticket;
    }
}

//+------------------------------------------------------------------+
//| Tick forwarding                                                  |
//+------------------------------------------------------------------+
void SendTick()
{
    string symbol  = Symbol();
    double bid     = SymbolInfoDouble(symbol, SYMBOL_BID);
    double ask     = SymbolInfoDouble(symbol, SYMBOL_ASK);
    long   bidVol  = (long)SymbolInfoDouble(symbol, SYMBOL_VOLUME_REAL);
    long   askVol  = bidVol; // MT5 does not always expose separate ask volume.
    long   timeMs  = (long)TimeCurrent() * 1000
                    + (long)(GetTickCount() % 1000);

    string tick = "{\"type\":\"tick\","
                + "\"symbol\":\"" + symbol + "\","
                + "\"bid\":\"" + DoubleToString(bid, 5) + "\","
                + "\"ask\":\"" + DoubleToString(ask, 5) + "\","
                + "\"bid_volume\":\"" + IntegerToString(bidVol) + "\","
                + "\"ask_volume\":\"" + IntegerToString(askVol) + "\","
                + "\"timestamp_ms\":" + IntegerToString(timeMs)
                + "}";

    SendLine(tick);
}

//+------------------------------------------------------------------+
//| Account update                                                   |
//+------------------------------------------------------------------+
void SendAccountUpdate()
{
    double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
    double margin     = AccountInfoDouble(ACCOUNT_MARGIN);
    double freeMargin = AccountInfoDouble(ACCOUNT_FREEMARGIN);
    long   timeMs     = (long)TimeCurrent() * 1000;

    string update = "{\"type\":\"account_update\","
                  + "\"balance\":\"" + DoubleToString(balance, 2) + "\","
                  + "\"equity\":\"" + DoubleToString(equity, 2) + "\","
                  + "\"margin\":\"" + DoubleToString(margin, 2) + "\","
                  + "\"free_margin\":\"" + DoubleToString(freeMargin, 2) + "\","
                  + "\"timestamp_ms\":" + IntegerToString(timeMs)
                  + "}";

    SendLine(update);
}

//+------------------------------------------------------------------+
//| TCP helpers                                                      |
//+------------------------------------------------------------------+
void SendLine(const string &msg)
{
    if (!g_connected) return;

    string out = msg + "\n";
    uchar  raw[];
    StringToCharArray(out, raw, 0, StringLen(out));

    if (DebugWire)
        Print("WIRE OUT: ", msg);

    int sent = SocketSend(g_clientSocket, raw, ArraySize(raw) - 1);
    if (sent < 0)
    {
        Print("QuantFundBridge: send failed, client disconnected");
        SocketClose(g_clientSocket);
        g_clientSocket = INVALID_HANDLE;
        g_connected    = false;
    }
}

long GetCurrentTimeMs()
{
    return (long)TimeCurrent() * 1000 + (long)(GetTickCount() % 1000);
}

//+------------------------------------------------------------------+
//| Minimal JSON field extractor                                     |
//| Extracts the string value of a top-level key from a flat JSON    |
//| object.  Does NOT handle nested objects.                         |
//+------------------------------------------------------------------+
string JsonGetString(const string &json, const string &key)
{
    string needle = "\"" + key + "\"";
    int pos = StringFind(json, needle);
    if (pos < 0) return "";

    pos += StringLen(needle);

    // Skip whitespace and colon.
    while (pos < StringLen(json) && (StringGetCharacter(json, pos) == ' '
        || StringGetCharacter(json, pos) == '\t'
        || StringGetCharacter(json, pos) == ':'))
        pos++;

    if (pos >= StringLen(json)) return "";

    ushort ch = StringGetCharacter(json, pos);

    if (ch == '"')
    {
        // String value.
        pos++;
        string result = "";
        while (pos < StringLen(json))
        {
            ushort c = StringGetCharacter(json, pos);
            if (c == '"') break;
            if (c == '\\') { pos++; c = StringGetCharacter(json, pos); }
            result += ShortToString(c);
            pos++;
        }
        return result;
    }
    else if (ch == 'n') // null
    {
        return "";
    }
    else
    {
        // Numeric or boolean: read until delimiter.
        string result = "";
        while (pos < StringLen(json))
        {
            ushort c = StringGetCharacter(json, pos);
            if (c == ',' || c == '}' || c == ']' || c == ' ' || c == '\n') break;
            result += ShortToString(c);
            pos++;
        }
        return result;
    }
}

//+------------------------------------------------------------------+
//| Parallel-array map: Rust OrderId (string) <-> MT5 ticket (ulong) |
//+------------------------------------------------------------------+
void MapSet(const string &rustId, ulong ticket)
{
    // Update existing entry if present.
    for (int i = 0; i < g_mapSize; i++)
    {
        if (g_rustIds[i] == rustId)
        {
            g_mt5Tickets[i] = ticket;
            return;
        }
    }

    // Insert new entry.
    if (g_mapSize < MAX_ORDERS)
    {
        g_rustIds[g_mapSize]    = rustId;
        g_mt5Tickets[g_mapSize] = ticket;
        g_mapSize++;
    }
    else
    {
        Print("QuantFundBridge: MapSet overflow — MAX_ORDERS reached");
    }
}

ulong MapGet(const string &rustId)
{
    for (int i = 0; i < g_mapSize; i++)
    {
        if (g_rustIds[i] == rustId)
            return g_mt5Tickets[i];
    }
    return 0;
}

string MapGetByTicket(ulong ticket)
{
    for (int i = 0; i < g_mapSize; i++)
    {
        if (g_mt5Tickets[i] == ticket)
            return g_rustIds[i];
    }
    return "";
}

void MapRemove(const string &rustId)
{
    for (int i = 0; i < g_mapSize; i++)
    {
        if (g_rustIds[i] == rustId)
        {
            // Shift remaining entries left.
            for (int j = i; j < g_mapSize - 1; j++)
            {
                g_rustIds[j]    = g_rustIds[j + 1];
                g_mt5Tickets[j] = g_mt5Tickets[j + 1];
            }
            g_mapSize--;
            return;
        }
    }
}
