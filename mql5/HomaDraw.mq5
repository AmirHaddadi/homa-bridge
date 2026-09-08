//+------------------------------------------------------------------+
//|                                                    HomaDraw.mq5   |
//|                                                   Project Meta5   |
//|                                                                  |
//|  Renders trend lines / rectangular order blocks / geometry that   |
//|  the Python bridge writes, so Claude can annotate the chart.      |
//|                                                                  |
//|  Data source:  <terminal>/MQL5/Files/homa_draw.tsv               |
//|  Producer:     mt5bridge/draw.py  (./run.sh draw ...)            |
//|                                                                  |
//|  One tab-separated line per shape:                                |
//|    id  type  symbol  color  width  style  fill  back  ray  font   |
//|        text  points                                              |
//|  where points = "YYYY.MM.DD HH:MM,price;YYYY.MM.DD HH:MM,price"   |
//|  type in: rect trend hline vline triangle ellipse text arrow      |
//|  color   : "R,G,B"  (0-255 each)  or  a few clr* names            |
//|                                                                  |
//|  Every object is named  HOMA_<id>  (+ HOMA_<id>_lbl for its       |
//|  caption). Objects with that prefix that are no longer in the     |
//|  file are deleted. Nothing else on the chart is touched.          |
//|  Attach to ONE chart per symbol (or a single chart if every       |
//|  shape carries an explicit symbol == that chart).                 |
//+------------------------------------------------------------------+
#property copyright "Project Meta5"
#property version   "1.00"
#property description "Draws bridge-supplied trend lines, order-block rectangles and geometry from MQL5/Files/homa_draw.tsv. View-only; places no trades."
#property strict

input string InpFile          = "homa_draw.tsv"; // File in MQL5/Files to read
input int    InpPollSeconds   = 1;               // Re-check the file every N seconds
input string InpPrefix        = "HOMA_";         // Object-name prefix this EA owns
input bool   InpMatchSymbol   = true;            // Only draw shapes for this chart's symbol (blank symbol = any)
input bool   InpDeleteOnRemove= true;            // Delete all owned objects when the EA is removed from the chart
input bool   InpFillDefault   = true;            // Fill rectangles/triangles unless the shape says otherwise

string g_last_content = "\x01";                   // force first pass

//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(MathMax(1, InpPollSeconds));
   Sync(true);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(InpDeleteOnRemove && (reason == REASON_REMOVE || reason == REASON_CHARTCLOSE))
      DeleteAllOwned();
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   Sync(false);
  }

//+------------------------------------------------------------------+
//| Read the file; if it changed, rebuild every owned object.         |
//+------------------------------------------------------------------+
void Sync(bool force)
  {
   string content;
   if(!ReadWhole(InpFile, content))
     {
      // file missing -> clear everything we own, once
      if(g_last_content != "")
        {
         DeleteAllOwned();
         g_last_content = "";
         ChartRedraw();
        }
      return;
     }

   if(!force && content == g_last_content)
      return;
   g_last_content = content;

   string seen[];                 // object names that must survive this pass
   string lines[];
   int n = StringSplit(content, '\n', lines);
   for(int i = 0; i < n; i++)
     {
      string ln = Trim(lines[i]);
      if(ln == "" || StringGetCharacter(ln, 0) == '#')
         continue;
      BuildShape(ln, seen);
     }

   PruneUnseen(seen);
   ChartRedraw();
  }

//+------------------------------------------------------------------+
bool ReadWhole(const string fname, string &out)
  {
   // Read as raw bytes and decode UTF-8 -- the producer (mt5bridge.draw) writes
   // UTF-8 so Persian labels survive; FILE_TXT/FILE_ANSI would mangle them.
   int h = FileOpen(fname, FILE_READ | FILE_BIN | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return(false);
   int sz = (int)FileSize(h);
   uchar buf[];
   ArrayResize(buf, sz);
   if(sz > 0)
      FileReadArray(h, buf, 0, sz);
   FileClose(h);
   // strip a UTF-8 BOM if present
   int start = (sz >= 3 && buf[0] == 0xEF && buf[1] == 0xBB && buf[2] == 0xBF) ? 3 : 0;
   out = CharArrayToString(buf, start, WHOLE_ARRAY, CP_UTF8);
   return(true);
  }

//+------------------------------------------------------------------+
//| Parse one line and create/update its object(s).                   |
//+------------------------------------------------------------------+
void BuildShape(const string line, string &seen[])
  {
   string f[];
   if(StringSplit(line, '\t', f) < 12)
      return;

   string id      = Trim(f[0]);
   string type    = Trim(f[1]);
   string sym     = Trim(f[2]);
   color  col     = ParseColor(Trim(f[3]));
   int    width   = (int)StringToInteger(f[4]);
   ENUM_LINE_STYLE style = ParseStyle(Trim(f[5]));
   bool   fill    = (Trim(f[6]) == "1");
   bool   back    = (Trim(f[7]) == "1");
   bool   ray     = (Trim(f[8]) == "1");
   int    font    = (int)StringToInteger(f[9]);
   string text    = Trim(f[10]);
   string ptsRaw  = Trim(f[11]);

   if(id == "" || type == "")
      return;
   if(InpMatchSymbol && sym != "" && sym != _Symbol)
      return;                                   // belongs to another chart

   datetime t[]; double p[];
   int np = ParsePoints(ptsRaw, t, p);
   if(np == 0 && type != "hline")
      return;

   string name = InpPrefix + id;
   ObjectDelete(0, name);                       // simplest correct: recreate

   bool ok = false;
   if(type == "rect")
      ok = MakeTwoPoint(name, OBJ_RECTANGLE, t, p, np);
   else if(type == "trend")
     {
      ok = MakeTwoPoint(name, OBJ_TREND, t, p, np);
      if(ok) ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, ray);
     }
   else if(type == "hline")
     {
      ok = ObjectCreate(0, name, OBJ_HLINE, 0, 0, p[0]);
     }
   else if(type == "vline")
      ok = ObjectCreate(0, name, OBJ_VLINE, 0, t[0], 0);
   else if(type == "triangle")
      ok = MakeNPoint(name, OBJ_TRIANGLE, t, p, np, 3);
   else if(type == "ellipse")
      ok = MakeNPoint(name, OBJ_ELLIPSE, t, p, np, 3);
   else if(type == "text")
     {
      ok = ObjectCreate(0, name, OBJ_TEXT, 0, t[0], p[0]);
      if(ok)
        {
         ObjectSetString(0, name, OBJPROP_TEXT, text);
         ObjectSetInteger(0, name, OBJPROP_FONTSIZE, font > 0 ? font : 10);
         ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT);
        }
     }
   else if(type == "arrow")
     {
      ok = ObjectCreate(0, name, OBJ_ARROW, 0, t[0], p[0]);
      if(ok) ObjectSetInteger(0, name, OBJPROP_ARROWCODE, 251);
     }

   if(!ok)
      return;

   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width > 0 ? width : 1);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_BACK, back);
   ObjectSetInteger(0, name, OBJPROP_FILL, fill && (type == "rect" || type == "triangle" || type == "ellipse"));
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   if(text != "")
      ObjectSetString(0, name, OBJPROP_TOOLTIP, text);

   Append(seen, name);

   // caption for area/line shapes
   string lbl = name + "_lbl";
   ObjectDelete(0, lbl);
   if(text != "" && (type == "rect" || type == "trend" || type == "hline"))
     {
      datetime lt = (np > 0 ? t[0] : (datetime)(TimeCurrent()));
      double   lp = p[0];
      if(ObjectCreate(0, lbl, OBJ_TEXT, 0, lt, lp))
        {
         ObjectSetString(0, lbl, OBJPROP_TEXT, " " + text);
         ObjectSetInteger(0, lbl, OBJPROP_COLOR, col);
         ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE, font > 0 ? font : 8);
         ObjectSetInteger(0, lbl, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
         ObjectSetInteger(0, lbl, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, lbl, OBJPROP_HIDDEN, true);
         ObjectSetInteger(0, lbl, OBJPROP_BACK, false);
         Append(seen, lbl);
        }
     }
  }

//+------------------------------------------------------------------+
bool MakeTwoPoint(const string name, ENUM_OBJECT kind, datetime &t[], double &p[], int np)
  {
   if(np < 2)
      return(false);
   if(!ObjectCreate(0, name, kind, 0, t[0], p[0], t[1], p[1]))
      return(false);
   return(true);
  }

//+------------------------------------------------------------------+
bool MakeNPoint(const string name, ENUM_OBJECT kind, datetime &t[], double &p[], int np, int need)
  {
   if(np < need)
      return(false);
   if(!ObjectCreate(0, name, kind, 0, t[0], p[0], t[1], p[1], t[2], p[2]))
      return(false);
   return(true);
  }

//+------------------------------------------------------------------+
int ParsePoints(const string raw, datetime &t[], double &p[])
  {
   ArrayResize(t, 0);
   ArrayResize(p, 0);
   if(raw == "")
      return(0);
   string chunks[];
   int c = StringSplit(raw, ';', chunks);
   for(int i = 0; i < c; i++)
     {
      string pair[];
      if(StringSplit(chunks[i], ',', pair) < 1)
         continue;
      datetime tt = (StringLen(Trim(pair[0])) > 0) ? StringToTime(Trim(pair[0])) : 0;
      double   pp = (ArraySize(pair) > 1 && StringLen(Trim(pair[1])) > 0) ? StringToDouble(pair[1]) : 0.0;
      int k = ArraySize(t);
      ArrayResize(t, k + 1);
      ArrayResize(p, k + 1);
      t[k] = tt;
      p[k] = pp;
     }
   return(ArraySize(t));
  }

//+------------------------------------------------------------------+
color ParseColor(const string s)
  {
   if(StringFind(s, ",") >= 0)
      return(StringToColor(s));                 // "R,G,B" -> color
   if(s == "clrRed")        return(clrRed);
   if(s == "clrOrangeRed")  return(clrOrangeRed);
   if(s == "clrLime")       return(clrLime);
   if(s == "clrDodgerBlue") return(clrDodgerBlue);
   if(s == "clrGold")       return(clrGold);
   if(s == "clrGray")       return(clrGray);
   if(s == "clrWhite")      return(clrWhite);
   return(clrSilver);
  }

//+------------------------------------------------------------------+
ENUM_LINE_STYLE ParseStyle(const string s)
  {
   if(s == "dash") return(STYLE_DASH);
   if(s == "dot")  return(STYLE_DOT);
   return(STYLE_SOLID);
  }

//+------------------------------------------------------------------+
//| helpers                                                           |
//+------------------------------------------------------------------+
string Trim(string s)
  {
   StringTrimLeft(s);
   StringTrimRight(s);
   return(s);
  }

void Append(string &arr[], const string v)
  {
   int k = ArraySize(arr);
   ArrayResize(arr, k + 1);
   arr[k] = v;
  }

bool InArray(const string &arr[], const string v)
  {
   for(int i = 0; i < ArraySize(arr); i++)
      if(arr[i] == v)
         return(true);
   return(false);
  }

//+------------------------------------------------------------------+
void PruneUnseen(const string &seen[])
  {
   int total = ObjectsTotal(0);
   for(int i = total - 1; i >= 0; i--)
     {
      string nm = ObjectName(0, i);
      if(StringFind(nm, InpPrefix) != 0)
         continue;
      if(!InArray(seen, nm))
         ObjectDelete(0, nm);
     }
  }

//+------------------------------------------------------------------+
void DeleteAllOwned()
  {
   int total = ObjectsTotal(0);
   for(int i = total - 1; i >= 0; i--)
     {
      string nm = ObjectName(0, i);
      if(StringFind(nm, InpPrefix) == 0)
         ObjectDelete(0, nm);
     }
  }
//+------------------------------------------------------------------+
