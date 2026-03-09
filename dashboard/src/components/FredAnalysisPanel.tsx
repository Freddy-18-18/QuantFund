import {
  Card,
  Title,
  Text,
  Metric,
  Grid,
  Col,
  Badge,
  ProgressBar,
  Flex,
  DonutChart,
  TabGroup,
  TabList,
  Tab,
  TabPanel,
  TabPanels,
} from "@tremor/react";

interface FredAnalysisPanelProps {
  stats: {
    min: number;
    max: number;
    mean: number;
    currentValue: number;
    percentileCurrent: number;
    zScoreCurrent: number;
  };
  yoyChange: number;
  momChange: number;
  dataPoints: number;
  lastUpdated: string;
  title: string;
}

function getZScoreBadge(zScore: number): { label: string; color: string } {
  if (zScore > 2) return { label: "EXTREME HIGH", color: "rose-500" };
  if (zScore < -2) return { label: "EXTREME LOW", color: "rose-500" };
  if (zScore >= -0.5 && zScore <= 0.5) return { label: "NEAR MEAN", color: "blue-500" };
  return zScore > 0 ? { label: "ABOVE AVERAGE", color: "amber-500" } : { label: "BELOW AVERAGE", color: "amber-500" };
}

function getPercentileLabel(percentile: number): { label: string; color: string } {
  if (percentile < 10) return { label: "Very Low", color: "rose-500" };
  if (percentile < 30) return { label: "Low", color: "orange-500" };
  if (percentile < 70) return { label: "Normal", color: "blue-500" };
  if (percentile < 90) return { label: "High", color: "amber-500" };
  return { label: "Very High", color: "rose-500" };
}

function formatNumber(value: number): string {
  if (Math.abs(value) >= 1e9) return (value / 1e9).toFixed(2) + "B";
  if (Math.abs(value) >= 1e6) return (value / 1e6).toFixed(2) + "M";
  if (Math.abs(value) >= 1e3) return (value / 1e3).toFixed(2) + "K";
  return value.toFixed(2);
}

export default function FredAnalysisPanel({
  stats,
  yoyChange,
  momChange,
  dataPoints,
  lastUpdated,
  title,
}: FredAnalysisPanelProps) {
  const zScoreBadge = getZScoreBadge(stats.zScoreCurrent);
  const percentileInfo = getPercentileLabel(stats.percentileCurrent);
  const valueRange = stats.max - stats.min;
  const currentPosition = valueRange > 0 ? ((stats.currentValue - stats.min) / valueRange) * 100 : 50;
  const meanPosition = valueRange > 0 ? ((stats.mean - stats.min) / valueRange) * 100 : 50;

  return (
    <Card className="bg-slate-900 border-slate-800">
      <Title className="text-slate-100">{title}</Title>
      <Text className="text-slate-400">Statistical analysis and historical context</Text>

      <TabGroup className="mt-4">
        <TabList variant="solid" className="bg-slate-800">
          <Tab className="text-slate-300 data-[selected]:bg-slate-700 data-[selected]:text-white">Overview</Tab>
          <Tab className="text-slate-300 data-[selected]:bg-slate-700 data-[selected]:text-white">Distribution</Tab>
          <Tab className="text-slate-300 data-[selected]:bg-slate-700 data-[selected]:text-white">Quality</Tab>
        </TabList>

        <TabPanels>
          <TabPanel>
            <Grid numItems={1} numItemsSm={2} numItemsLg={3} className="gap-4 mt-4">
              <Col>
                <Card className="bg-slate-800 border-slate-700">
                  <Flex justifyContent="between" alignItems="center">
                    <Text className="text-slate-400">Current Value</Text>
                    <Badge color={yoyChange >= 0 ? "emerald" : "rose"}>
                      {yoyChange >= 0 ? "+" : ""}{yoyChange.toFixed(2)}% YoY
                    </Badge>
                  </Flex>
                  <Metric className="text-3xl text-white mt-2">{formatNumber(stats.currentValue)}</Metric>
                  <Flex justifyContent="between" className="mt-2">
                    <Badge color={momChange >= 0 ? "emerald" : "rose"} size="xs">
                      {momChange >= 0 ? "+" : ""}{momChange.toFixed(2)}% MoM
                    </Badge>
                    <Text className="text-slate-500">{stats.percentileCurrent.toFixed(1)}th percentile</Text>
                  </Flex>
                </Card>
              </Col>

              <Col>
                <Card className="bg-slate-800 border-slate-700">
                  <Flex justifyContent="between" alignItems="center">
                    <Text className="text-slate-400">Z-Score</Text>
                    <Badge color={zScoreBadge.color === "rose-500" ? "rose" : zScoreBadge.color === "blue-500" ? "blue" : "amber"}>
                      {zScoreBadge.label}
                    </Badge>
                  </Flex>
                  <Metric className="text-3xl text-white mt-2">{stats.zScoreCurrent.toFixed(2)}σ</Metric>
                  <Text className="text-slate-500 mt-1">
                    {stats.zScoreCurrent > 0 ? "Above" : "Below"} mean by {Math.abs(stats.zScoreCurrent).toFixed(2)} standard deviations
                  </Text>
                  <div className="mt-3">
                    <ProgressBar 
                      value={Math.min(Math.max((stats.zScoreCurrent + 3) / 6 * 100, 0), 100)} 
                      color="blue"
                      className="bg-slate-700"
                    />
                    <Flex className="mt-1">
                      <Text className="text-xs text-slate-500">-3σ</Text>
                      <Text className="text-xs text-slate-500">0</Text>
                      <Text className="text-xs text-slate-500">+3σ</Text>
                    </Flex>
                  </div>
                </Card>
              </Col>

              <Col>
                <Card className="bg-slate-800 border-slate-700">
                  <Flex justifyContent="between" alignItems="center">
                    <Text className="text-slate-400">Percentile</Text>
                    <Badge color={percentileInfo.color === "rose-500" ? "rose" : percentileInfo.color === "orange-500" ? "orange" : percentileInfo.color === "amber-500" ? "amber" : "blue"}>
                      {percentileInfo.label}
                    </Badge>
                  </Flex>
                  <Metric className="text-3xl text-white mt-2">{stats.percentileCurrent.toFixed(1)}</Metric>
                  <div className="mt-3">
                    <ProgressBar 
                      value={stats.percentileCurrent} 
                      color={percentileInfo.color === "rose-500" ? "rose" : percentileInfo.color === "orange-500" ? "orange" : percentileInfo.color === "amber-500" ? "amber" : "blue"}
                      className="bg-slate-700"
                    />
                    <Flex className="mt-1">
                      <Text className="text-xs text-slate-500">0</Text>
                      <Text className="text-xs text-slate-500">50</Text>
                      <Text className="text-xs text-slate-500">100</Text>
                    </Flex>
                  </div>
                </Card>
              </Col>
            </Grid>

            <Card className="bg-slate-800 border-slate-700 mt-4">
              <Title className="text-slate-200">Historical Range</Title>
              <Grid numItems={2} className="mt-4 gap-4">
                <div>
                  <Text className="text-slate-400">Minimum</Text>
                  <Metric className="text-xl text-slate-300">{formatNumber(stats.min)}</Metric>
                </div>
                <div>
                  <Text className="text-slate-400">Maximum</Text>
                  <Metric className="text-xl text-slate-300">{formatNumber(stats.max)}</Metric>
                </div>
                <div>
                  <Text className="text-slate-400">Mean</Text>
                  <Metric className="text-xl text-blue-400">{formatNumber(stats.mean)}</Metric>
                </div>
                <div>
                  <Text className="text-slate-400">Range</Text>
                  <Metric className="text-xl text-slate-300">{formatNumber(valueRange)}</Metric>
                </div>
              </Grid>
              
              <div className="mt-4">
                <Text className="text-slate-400 mb-2">Value Position</Text>
                <div className="relative h-8 bg-slate-700 rounded">
                  <div 
                    className="absolute h-full bg-slate-600"
                    style={{ left: currentPosition < meanPosition ? `${currentPosition}%` : `${meanPosition}%`,
                             width: `${Math.abs(meanPosition - currentPosition)}%` }}
                  />
                  <div 
                    className="absolute top-0 h-full w-1 bg-blue-500"
                    style={{ left: `${meanPosition}%` }}
                    title="Mean"
                  />
                  <div 
                    className="absolute top-0 h-full w-2 bg-white border-2 border-slate-900"
                    style={{ left: `${currentPosition}%`, transform: 'translateX(-50%)' }}
                    title="Current"
                  />
                </div>
                <Flex className="mt-1">
                  <Text className="text-xs text-slate-500">Min</Text>
                  <Text className="text-xs text-blue-400">Mean</Text>
                  <Text className="text-xs text-slate-500">Max</Text>
                </Flex>
              </div>
            </Card>
          </TabPanel>

          <TabPanel>
            <Grid numItems={1} numItemsSm={2} className="gap-4 mt-4">
              <Card className="bg-slate-800 border-slate-700">
                <Title className="text-slate-200">Distribution</Title>
                <DonutChart
                  className="mt-4 h-40"
                  data={[
                    { name: "Below Mean", value: stats.mean - stats.min },
                    { name: "Above Mean", value: stats.max - stats.mean },
                  ]}
                  category="value"
                  index="name"
                  colors={["slate", "blue"]}
                  valueFormatter={(value) => formatNumber(value)}
                  showAnimation
                />
                <Flex className="mt-4">
                  <div>
                    <Text className="text-slate-400">Below Mean Range</Text>
                    <Metric className="text-lg text-slate-300">{formatNumber(stats.mean - stats.min)}</Metric>
                  </div>
                  <div>
                    <Text className="text-slate-400">Above Mean Range</Text>
                    <Metric className="text-lg text-slate-300">{formatNumber(stats.max - stats.mean)}</Metric>
                  </div>
                </Flex>
              </Card>

              <Card className="bg-slate-800 border-slate-700">
                <Title className="text-slate-200">Value Analysis</Title>
                <div className="mt-4 space-y-4">
                  <div>
                    <Flex>
                      <Text className="text-slate-400">Distance from Mean</Text>
                      <Text className="text-white">{formatNumber(Math.abs(stats.currentValue - stats.mean))}</Text>
                    </Flex>
                    <ProgressBar 
                      value={Math.min((Math.abs(stats.currentValue - stats.mean) / valueRange) * 100, 100)} 
                      color="blue"
                      className="mt-1 bg-slate-700"
                    />
                  </div>
                  <div>
                    <Flex>
                      <Text className="text-slate-400">Position in Range</Text>
                      <Text className="text-white">{currentPosition.toFixed(1)}%</Text>
                    </Flex>
                    <ProgressBar 
                      value={currentPosition} 
                      color="slate"
                      className="mt-1 bg-slate-700"
                    />
                  </div>
                  <div>
                    <Flex>
                      <Text className="text-slate-400">Std. Deviation</Text>
                      <Text className="text-white">{((stats.max - stats.min) / 4).toFixed(2)}</Text>
                    </Flex>
                  </div>
                </div>
              </Card>
            </Grid>
          </TabPanel>

          <TabPanel>
            <Grid numItems={1} numItemsSm={2} className="gap-4 mt-4">
              <Card className="bg-slate-800 border-slate-700">
                <Title className="text-slate-200">Data Quality</Title>
                <div className="mt-4">
                  <Flex>
                    <Text className="text-slate-400">Total Data Points</Text>
                    <Metric className="text-xl text-white">{dataPoints.toLocaleString()}</Metric>
                  </Flex>
                  <ProgressBar 
                    value={Math.min((dataPoints / 500) * 100, 100)} 
                    color={dataPoints > 300 ? "emerald" : dataPoints > 100 ? "amber" : "rose"}
                    className="mt-2 bg-slate-700"
                  />
                  <Text className="text-sm text-slate-500 mt-2">
                    {dataPoints > 300 ? "Excellent data coverage" : dataPoints > 100 ? "Adequate data coverage" : "Limited data coverage"}
                  </Text>
                </div>

                <div className="mt-6">
                  <Flex>
                    <Text className="text-slate-400">Last Updated</Text>
                    <Text className="text-white">{lastUpdated}</Text>
                  </Flex>
                </div>
              </Card>

              <Card className="bg-slate-800 border-slate-700">
                <Title className="text-slate-200">Summary Statistics</Title>
                <div className="mt-4 space-y-3">
                  <Flex>
                    <Text className="text-slate-400">Minimum</Text>
                    <Text className="text-white">{formatNumber(stats.min)}</Text>
                  </Flex>
                  <Flex>
                    <Text className="text-slate-400">Maximum</Text>
                    <Text className="text-white">{formatNumber(stats.max)}</Text>
                  </Flex>
                  <Flex>
                    <Text className="text-slate-400">Mean</Text>
                    <Text className="text-blue-400">{formatNumber(stats.mean)}</Text>
                  </Flex>
                  <Flex>
                    <Text className="text-slate-400">Range</Text>
                    <Text className="text-white">{formatNumber(valueRange)}</Text>
                  </Flex>
                  <Flex>
                    <Text className="text-slate-400">Coefficient of Var.</Text>
                    <Text className="text-white">{valueRange > 0 && stats.mean !== 0 ? ((valueRange / Math.abs(stats.mean)) * 100).toFixed(2) + "%" : "N/A"}</Text>
                  </Flex>
                </div>
              </Card>
            </Grid>
          </TabPanel>
        </TabPanels>
      </TabGroup>
    </Card>
  );
}
