import { useState } from "react";
import {
  Card,
  Title,
  Text,
  Metric,
  Grid,
  Col,
  Badge,
  AreaChart,
  BarChart,
  Flex,
  ProgressBar,
  TabGroup,
  TabList,
  Tab,
  TabPanel,
  TabPanels,
  DonutChart,
  List,
  ListItem,
} from "@tremor/react";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Database,
  RefreshCw,
  Calendar,
  BarChart3,
  Activity,
  CheckCircle2,
  Clock,
} from "lucide-react";

export interface FredDashboardProps {
  seriesId: string;
  title: string;
  currentValue: number;
  previousValue: number;
  yoyChange: number;
  momChange: number;
  percentile: number;
  zScore: number;
  frequency: string;
  units: string;
  lastUpdated: string;
  observations: { date: string; value: number }[];
  yoyData: { date: string; value: number }[];
  momData: { date: string; value: number }[];
  categories?: { name: string }[];
  onSeriesChange?: (seriesId: string) => void;
}

interface StatItem {
  label: string;
  value: string | number;
  color?: "blue" | "emerald" | "amber" | "rose" | "gray";
}

function formatValue(value: number, units: string): string {
  if (units === "Percent" || units === "%") {
    return `${value.toFixed(2)}%`;
  }
  if (Math.abs(value) >= 1e9) {
    return `${(value / 1e9).toFixed(2)}B`;
  }
  if (Math.abs(value) >= 1e6) {
    return `${(value / 1e6).toFixed(2)}M`;
  }
  if (Math.abs(value) >= 1e3) {
    return `${(value / 1e3).toFixed(2)}K`;
  }
  return value.toFixed(2);
}

function getChangeColor(change: number): "emerald" | "rose" | "gray" {
  if (change > 0) return "emerald";
  if (change < 0) return "rose";
  return "gray";
}

function getChangeIcon(change: number) {
  if (change > 0) return TrendingUp;
  if (change < 0) return TrendingDown;
  return Minus;
}

function calculateStats(data: { date: string; value: number }[]): StatItem[] {
  if (!data || data.length === 0) {
    return [
      { label: "Min", value: "N/A", color: "gray" },
      { label: "Max", value: "N/A", color: "gray" },
      { label: "Mean", value: "N/A", color: "gray" },
      { label: "Count", value: "N/A", color: "gray" },
    ];
  }

  const values = data.map((d) => d.value).filter((v) => v !== null && !isNaN(v));
  if (values.length === 0) {
    return [
      { label: "Min", value: "N/A", color: "gray" },
      { label: "Max", value: "N/A", color: "gray" },
      { label: "Mean", value: "N/A", color: "gray" },
      { label: "Count", value: "N/A", color: "gray" },
    ];
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;

  return [
    { label: "Min", value: min.toFixed(2), color: "rose" },
    { label: "Max", value: max.toFixed(2), color: "emerald" },
    { label: "Mean", value: mean.toFixed(2), color: "blue" },
    { label: "Count", value: values.length, color: "gray" },
  ];
}

function SyncStatusCard() {
  const [isSyncing, setIsSyncing] = useState(false);
  const [lastSync] = useState(new Date().toISOString());

  const handleSync = () => {
    setIsSyncing(true);
    setTimeout(() => {
      setIsSyncing(false);
    }, 2000);
  };

  return (
    <Card className="bg-slate-900 border-slate-800">
      <Flex justifyContent="between" alignItems="center">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500/10 rounded-lg">
            <Database className="w-5 h-5 text-emerald-500" />
          </div>
          <div>
            <Text className="text-slate-400">Database Sync</Text>
            <Flex justifyContent="start" className="gap-2 mt-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
              <Text className="text-xs text-emerald-500">Connected</Text>
            </Flex>
          </div>
        </div>
        <button
          onClick={handleSync}
          disabled={isSyncing}
          className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white text-sm font-medium rounded-md transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${isSyncing ? "animate-spin" : ""}`} />
          {isSyncing ? "Syncing..." : "Sync Now"}
        </button>
      </Flex>
      <div className="mt-4 pt-4 border-t border-slate-800">
        <Flex justifyContent="between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-500" />
            <Text className="text-slate-500 text-sm">Last sync:</Text>
          </div>
          <Text className="text-slate-400 text-sm">
            {new Date(lastSync).toLocaleString()}
          </Text>
        </Flex>
      </div>
    </Card>
  );
}

export function FredProfessionalDashboard({
  seriesId,
  title,
  currentValue,
  previousValue,
  yoyChange,
  momChange,
  percentile,
  zScore,
  frequency,
  units,
  lastUpdated,
  observations,
  yoyData,
  momData,
  categories = [],
}: FredDashboardProps) {
  const [selectedTab, setSelectedTab] = useState(0);

  const isLoading = !observations || observations.length === 0;
  const stats = calculateStats(observations);
  const ChangeIcon = getChangeIcon(yoyChange);
  const changeColor = getChangeColor(yoyChange);

  const chartColors = ["blue-500", "emerald-500", "amber-500", "rose-500"] as const;

  return (
    <div className="space-y-6">
      <Grid numItems={1} numItemsLg={3} className="gap-6">
        <Col numColSpan={1} numColSpanLg={2}>
          <Card className="bg-slate-900 border-slate-800 h-full">
            <Flex justifyContent="between" alignItems="start">
              <div>
                <Text className="text-slate-400 uppercase tracking-wider text-sm">
                  {seriesId}
                </Text>
                <Title className="text-white mt-1">{title}</Title>
                <Flex justifyContent="start" className="mt-2 gap-3">
                  <Badge color={changeColor as "emerald" | "rose" | "gray"}>
                    <ChangeIcon className="w-3.5 h-3.5 mr-1" />
                    YoY: {yoyChange >= 0 ? "+" : ""}
                    {yoyChange.toFixed(2)}%
                  </Badge>
                  <Badge color={getChangeColor(momChange) as "emerald" | "rose" | "gray"}>
                    MoM: {momChange >= 0 ? "+" : ""}
                    {momChange.toFixed(2)}%
                  </Badge>
                </Flex>
              </div>
              <div className="text-right">
                <Text className="text-slate-400">Current Value</Text>
                <Metric className="text-3xl text-white mt-1">
                  {formatValue(currentValue, units)}
                </Metric>
                <Text className="text-slate-500 text-sm mt-1">
                  Previous: {formatValue(previousValue, units)}
                </Text>
              </div>
            </Flex>
          </Card>
        </Col>

        <Col numColSpan={1}>
          <Card className="bg-slate-900 border-slate-800 h-full">
            <Flex justifyContent="between" alignItems="center" className="mb-4">
              <Text className="text-slate-400">Statistical Summary</Text>
              <Activity className="w-4 h-4 text-slate-500" />
            </Flex>
            <div className="space-y-3">
              {stats.map((stat, idx) => (
                <Flex
                  key={stat.label}
                  justifyContent="between"
                  className={idx < stats.length - 1 ? "pb-3 border-b border-slate-800" : ""}
                >
                  <Text className="text-slate-400">{stat.label}</Text>
                  <Text color={stat.color as "blue" | "emerald" | "amber" | "rose" | "gray"}>
                    {stat.value}
                  </Text>
                </Flex>
              ))}
            </div>
            <div className="mt-4 pt-4 border-t border-slate-800">
              <Flex justifyContent="between" className="mb-2">
                <Text className="text-slate-400">Percentile</Text>
                <Text className="text-blue-400">{percentile.toFixed(1)}%</Text>
              </Flex>
              <ProgressBar value={percentile} color="blue" />
            </div>
            <div className="mt-4">
              <Flex justifyContent="between" className="mb-2">
                <Text className="text-slate-400">Z-Score</Text>
                <Text
                  color={
                    zScore > 1 || zScore < -1
                      ? "rose"
                      : zScore > 0.5 || zScore < -0.5
                      ? "amber"
                      : "emerald"
                  }
                >
                  {zScore.toFixed(2)}
                </Text>
              </Flex>
              <ProgressBar
                value={Math.min(Math.abs(zScore) * 25, 100)}
                color={zScore > 1 || zScore < -1 ? "rose" : zScore > 0.5 || zScore < -0.5 ? "amber" : "emerald"}
              />
            </div>
          </Card>
        </Col>
      </Grid>

      <Card className="bg-slate-900 border-slate-800">
        <Flex justifyContent="between" alignItems="center" className="mb-4">
          <div>
            <Title className="text-white">Historical Trend</Title>
            <Text className="text-slate-400">Value over time</Text>
          </div>
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-slate-500" />
            <Text className="text-slate-500 text-sm">Last Updated: {lastUpdated}</Text>
          </div>
        </Flex>
        {isLoading ? (
          <div className="h-80 flex items-center justify-center">
            <div className="flex items-center gap-2 text-slate-500">
              <RefreshCw className="w-5 h-5 animate-spin" />
              <Text>Loading data...</Text>
            </div>
          </div>
        ) : (
          <AreaChart
            className="h-80"
            data={observations}
            index="date"
            categories={["value"]}
            colors={[chartColors[0]]}
            valueFormatter={(value) => formatValue(value, units)}
            showLegend={false}
            showGridLines={true}
            curveType="monotone"
          />
        )}
      </Card>

      <Grid numItems={1} numItemsMd={2} className="gap-6">
        <Card className="bg-slate-900 border-slate-800">
          <Title className="text-white mb-4">Year-over-Year Change</Title>
          {isLoading ? (
            <div className="h-60 flex items-center justify-center">
              <div className="flex items-center gap-2 text-slate-500">
                <RefreshCw className="w-5 h-5 animate-spin" />
                <Text>Loading...</Text>
              </div>
            </div>
          ) : (
            <BarChart
              className="h-60"
              data={yoyData}
              index="date"
              categories={["value"]}
              colors={[chartColors[1]]}
              valueFormatter={(value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`}
              showLegend={false}
            />
          )}
        </Card>

        <Card className="bg-slate-900 border-slate-800">
          <Title className="text-white mb-4">Month-over-Month Change</Title>
          {isLoading ? (
            <div className="h-60 flex items-center justify-center">
              <div className="flex items-center gap-2 text-slate-500">
                <RefreshCw className="w-5 h-5 animate-spin" />
                <Text>Loading...</Text>
              </div>
            </div>
          ) : (
            <BarChart
              className="h-60"
              data={momData}
              index="date"
              categories={["value"]}
              colors={[chartColors[2]]}
              valueFormatter={(value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`}
              showLegend={false}
            />
          )}
        </Card>
      </Grid>

      <Grid numItems={1} numItemsLg={2} className="gap-6">
        <Card className="bg-slate-900 border-slate-800">
          <Flex justifyContent="between" alignItems="center" className="mb-4">
            <div>
              <Title className="text-white">Distribution Analysis</Title>
              <Text className="text-slate-400">Value distribution</Text>
            </div>
            <BarChart3 className="w-5 h-5 text-slate-500" />
          </Flex>
          {isLoading ? (
            <div className="h-60 flex items-center justify-center">
              <div className="flex items-center gap-2 text-slate-500">
                <RefreshCw className="w-5 h-5 animate-spin" />
                <Text>Loading...</Text>
              </div>
            </div>
          ) : observations && observations.length > 0 ? (
            <DonutChart
              className="h-60"
              data={observations.slice(-12).map((obs) => ({
                name: obs.date,
                value: obs.value,
              }))}
              category="value"
              index="name"
              colors={[...chartColors]}
              valueFormatter={(value) => formatValue(value, units)}
            />
          ) : (
            <div className="h-60 flex items-center justify-center">
              <Text className="text-slate-500">No data available</Text>
            </div>
          )}
        </Card>

        <div className="space-y-6">
          <Card className="bg-slate-900 border-slate-800">
            <Flex justifyContent="between" alignItems="center" className="mb-4">
              <div>
                <Title className="text-white">Metadata</Title>
                <Text className="text-slate-400">Series information</Text>
              </div>
            </Flex>
            <List>
              <ListItem>
                <Text className="text-slate-400">Frequency</Text>
                <Badge color="blue">{frequency}</Badge>
              </ListItem>
              <ListItem>
                <Text className="text-slate-400">Units</Text>
                <Badge color="emerald">{units}</Badge>
              </ListItem>
              <ListItem>
                <Text className="text-slate-400">Series ID</Text>
                <Text className="text-slate-300 font-mono">{seriesId}</Text>
              </ListItem>
            </List>
          </Card>

          {categories.length > 0 && (
            <Card className="bg-slate-900 border-slate-800">
              <Title className="text-white mb-4">Categories</Title>
              <div className="flex flex-wrap gap-2">
                {categories.map((cat, idx) => (
                  <Badge key={idx} color="slate">
                    {cat.name}
                  </Badge>
                ))}
              </div>
            </Card>
          )}

          <SyncStatusCard />
        </div>
      </Grid>

      <Card className="bg-slate-900 border-slate-800">
        <Title className="text-white mb-4">Recent Observations</Title>
        {isLoading ? (
          <div className="h-40 flex items-center justify-center">
            <div className="flex items-center gap-2 text-slate-500">
              <RefreshCw className="w-5 h-5 animate-spin" />
              <Text>Loading...</Text>
            </div>
          </div>
        ) : (
          <TabGroup index={selectedTab} onIndexChange={setSelectedTab}>
            <TabList variant="solid" color="blue">
              <Tab>All Data</Tab>
              <Tab>YoY Changes</Tab>
              <Tab>MoM Changes</Tab>
            </TabList>
            <TabPanels className="mt-4">
              <TabPanel>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-800">
                        <th className="text-left py-3 px-4 text-slate-400 font-medium text-sm">
                          Date
                        </th>
                        <th className="text-right py-3 px-4 text-slate-400 font-medium text-sm">
                          Value
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {observations?.slice(-10).reverse().map((obs, idx) => (
                        <tr
                          key={idx}
                          className="border-b border-slate-800/50 hover:bg-slate-800/30"
                        >
                          <td className="py-3 px-4 text-slate-300">{obs.date}</td>
                          <td className="py-3 px-4 text-right text-white font-mono">
                            {formatValue(obs.value, units)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </TabPanel>
              <TabPanel>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-800">
                        <th className="text-left py-3 px-4 text-slate-400 font-medium text-sm">
                          Date
                        </th>
                        <th className="text-right py-3 px-4 text-slate-400 font-medium text-sm">
                          YoY Change
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {yoyData?.slice(-10).reverse().map((item, idx) => (
                        <tr
                          key={idx}
                          className="border-b border-slate-800/50 hover:bg-slate-800/30"
                        >
                          <td className="py-3 px-4 text-slate-300">{item.date}</td>
                          <td
                            className={`py-3 px-4 text-right font-mono ${
                              item.value >= 0 ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {item.value >= 0 ? "+" : ""}
                            {item.value.toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </TabPanel>
              <TabPanel>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-800">
                        <th className="text-left py-3 px-4 text-slate-400 font-medium text-sm">
                          Date
                        </th>
                        <th className="text-right py-3 px-4 text-slate-400 font-medium text-sm">
                          MoM Change
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {momData?.slice(-10).reverse().map((item, idx) => (
                        <tr
                          key={idx}
                          className="border-b border-slate-800/50 hover:bg-slate-800/30"
                        >
                          <td className="py-3 px-4 text-slate-300">{item.date}</td>
                          <td
                            className={`py-3 px-4 text-right font-mono ${
                              item.value >= 0 ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {item.value >= 0 ? "+" : ""}
                            {item.value.toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </TabPanel>
            </TabPanels>
          </TabGroup>
        )}
      </Card>
    </div>
  );
}

export default FredProfessionalDashboard;
