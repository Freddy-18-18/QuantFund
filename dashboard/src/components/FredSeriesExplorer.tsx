import { useState, useMemo } from "react";
import {
  Card,
  Title,
  Text,
  Grid,
  Col,
  Badge,
  List,
  ListItem,
  Button,
  TextInput,
  Flex,
} from "@tremor/react";
import {
  Search,
  Folder,
  TrendingUp,
  BarChart3,
  Activity,
  Loader2,
} from "lucide-react";

export interface FredSeriesExplorerProps {
  categories: { id: number; name: string }[];
  seriesList: { id: string; title: string }[];
  selectedSeries: string;
  onSelectSeries: (seriesId: string) => void;
  isLoading?: boolean;
}

const QUICK_ACCESS_CATEGORIES = [
  {
    name: "Interest Rates",
    icon: TrendingUp,
    series: ["FEDFUNDS", "DGS10", "T10Y2Y"],
    color: "blue" as const,
  },
  {
    name: "Employment",
    icon: Activity,
    series: ["UNRATE", "PAYEMS", "CES0500000003"],
    color: "emerald" as const,
  },
  {
    name: "GDP",
    icon: BarChart3,
    series: ["GDPC1", "GDPPOT", "NGDP"],
    color: "amber" as const,
  },
  {
    name: "Prices",
    icon: Folder,
    series: ["CPIAUCSL", "PCEPI", "GOLDAMGBD228NLBM"],
    color: "rose" as const,
  },
  {
    name: "Consumer",
    icon: TrendingUp,
    series: ["CSUSHPINSA", "HOUST", "PERMIT"],
    color: "violet" as const,
  },
];

const POPULAR_SERIES = [
  { id: "GDPC1", title: "Real Gross Domestic Product" },
  { id: "CPIAUCSL", title: "Consumer Price Index for All Urban Consumers" },
  { id: "UNRATE", title: "Unemployment Rate" },
  { id: "FEDFUNDS", title: "Federal Funds Rate" },
  { id: "DGS10", title: "10-Year Treasury Constant Maturity Rate" },
];

export function FredSeriesExplorer({
  categories: _categories,
  seriesList,
  selectedSeries,
  onSelectSeries,
  isLoading = false,
}: FredSeriesExplorerProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchValue, setSearchValue] = useState("");

  const filteredSeries = useMemo(() => {
    if (!searchQuery) return [];
    const query = searchQuery.toLowerCase();
    return seriesList
      .filter(
        (s) =>
          s.id.toLowerCase().includes(query) ||
          s.title.toLowerCase().includes(query)
      )
      .slice(0, 10);
  }, [searchQuery, seriesList]);

  const getSeriesTitle = (seriesId: string): string => {
    const found = seriesList.find((s) => s.id === seriesId);
    return found?.title || seriesId;
  };

  const handleQuickAccess = (seriesIds: string[]) => {
    if (seriesIds.length > 0) {
      onSelectSeries(seriesIds[0]);
    }
  };

  const handlePopularClick = (seriesId: string) => {
    onSelectSeries(seriesId);
  };

  return (
    <Card className="bg-slate-900 border-slate-800">
      <Flex justifyContent="between" alignItems="center" className="mb-6">
        <div>
          <Title className="text-white">FRED Series Explorer</Title>
          <Text className="text-slate-400">Search and browse economic data series</Text>
        </div>
        {isLoading && (
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            <Text className="text-sm">Loading...</Text>
          </div>
        )}
      </Flex>

      <Grid numItems={1} numItemsLg={2} className="gap-6 mb-6">
        <Col>
          <div className="space-y-4">
            <div>
              <Text className="text-slate-400 mb-2 block text-sm font-medium">
                Quick Search
              </Text>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <TextInput
                  placeholder="Search series by ID or name..."
                  value={searchValue}
                  onChange={(e) => setSearchValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && filteredSeries.length > 0) {
                      onSelectSeries(filteredSeries[0].id);
                      setSearchQuery("");
                      setSearchValue("");
                    }
                  }}
                  className="pl-10 bg-slate-800 border-slate-700 text-white placeholder:text-slate-500"
                />
              </div>
              {searchQuery && filteredSeries.length > 0 && (
                <Card className="absolute z-10 mt-1 w-full bg-slate-800 border-slate-700 shadow-xl">
                  <List>
                    {filteredSeries.map((series) => (
                      <ListItem
                        key={series.id}
                        className="hover:bg-slate-700 cursor-pointer rounded-md"
                        onClick={() => {
                          onSelectSeries(series.id);
                          setSearchQuery("");
                          setSearchValue("");
                        }}
                      >
                        <div>
                          <Text className="text-white font-mono">{series.id}</Text>
                          <Text className="text-slate-400 text-sm truncate">
                            {series.title}
                          </Text>
                        </div>
                      </ListItem>
                    ))}
                  </List>
                </Card>
              )}
              {searchQuery && searchValue && filteredSeries.length === 0 && !isLoading && (
                <Card className="absolute z-10 mt-1 w-full bg-slate-800 border-slate-700">
                  <Text className="text-slate-400 text-sm">No series found</Text>
                </Card>
              )}
            </div>
          </div>
        </Col>

        <Col>
          <div>
            <Text className="text-slate-400 mb-2 block text-sm font-medium">
              Browse by Category
            </Text>
            <div className="flex flex-wrap gap-2">
              {QUICK_ACCESS_CATEGORIES.map((category) => (
                <Button
                  key={category.name}
                  variant="secondary"
                  size="xs"
                  className={`bg-slate-800 border-slate-700 hover:bg-slate-700`}
                  onClick={() => handleQuickAccess(category.series)}
                >
                  <category.icon className={`w-3.5 h-3.5 mr-1.5 text-${category.color}-400`} />
                  {category.name}
                </Button>
              ))}
            </div>
          </div>
        </Col>
      </Grid>

      <Grid numItems={1} numItemsLg={2} className="gap-6">
        <Col>
          <Card className="bg-slate-800 border-slate-700 h-full">
            <Flex justifyContent="between" alignItems="center" className="mb-4">
              <Title className="text-white text-base">Quick Access</Title>
              <Badge color="blue">{POPULAR_SERIES.length} series</Badge>
            </Flex>
            <div className="space-y-1">
              {QUICK_ACCESS_CATEGORIES.map((category) => (
                <div key={category.name} className="mb-4 last:mb-0">
                  <Flex className="mb-2">
                    <div className="flex items-center gap-2">
                      <category.icon className={`w-4 h-4 text-${category.color}-400`} />
                      <Text className="text-slate-300 font-medium text-sm">
                        {category.name}
                      </Text>
                    </div>
                  </Flex>
                  <div className="ml-6 space-y-1">
                    {category.series.map((seriesId) => {
                      const isSelected = selectedSeries === seriesId;
                      return (
                        <button
                          key={seriesId}
                          onClick={() => handlePopularClick(seriesId)}
                          className={`w-full text-left px-3 py-2 rounded-md transition-colors ${
                            isSelected
                              ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
                              : "hover:bg-slate-700 text-slate-300 hover:text-white"
                          }`}
                        >
                          <Flex justifyContent="between" alignItems="center">
                            <Text
                              className={`font-mono text-sm ${
                                isSelected ? "text-blue-400" : "text-slate-300"
                              }`}
                            >
                              {seriesId}
                            </Text>
                            {isSelected && (
                              <Badge color="blue" size="xs">
                                Selected
                              </Badge>
                            )}
                          </Flex>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </Col>

        <Col>
          <Card className="bg-slate-800 border-slate-700 h-full">
            <Flex justifyContent="between" alignItems="center" className="mb-4">
              <Title className="text-white text-base">Popular Series</Title>
              <TrendingUp className="w-4 h-4 text-slate-500" />
            </Flex>
            <List>
              {POPULAR_SERIES.map((series) => {
                const isSelected = selectedSeries === series.id;
                return (
                  <ListItem
                    key={series.id}
                    className={`hover:bg-slate-700 rounded-md cursor-pointer transition-colors ${
                      isSelected ? "bg-blue-600/10 border border-blue-600/20" : ""
                    }`}
                    onClick={() => handlePopularClick(series.id)}
                  >
                    <div className="flex-1 min-w-0">
                      <Flex justifyContent="between" alignItems="start">
                        <div className="flex-1 min-w-0">
                          <Text
                            className={`font-mono text-sm ${
                              isSelected ? "text-blue-400" : "text-slate-300"
                            }`}
                          >
                            {series.id}
                          </Text>
                          <Text className="text-slate-400 text-sm truncate">
                            {series.title}
                          </Text>
                        </div>
                        {isSelected && (
                          <Badge color="blue" size="xs">
                            Active
                          </Badge>
                        )}
                      </Flex>
                    </div>
                  </ListItem>
                );
              })}
            </List>
          </Card>
        </Col>
      </Grid>

      {selectedSeries && (
        <div className="mt-6 pt-4 border-t border-slate-800">
          <Flex justifyContent="between" alignItems="center">
            <div>
              <Text className="text-slate-400 text-sm">Selected Series</Text>
              <Title className="text-white">{selectedSeries}</Title>
              <Text className="text-slate-400 text-sm">{getSeriesTitle(selectedSeries)}</Text>
            </div>
            <Button
              color="blue"
              onClick={() => onSelectSeries(selectedSeries)}
              className="bg-blue-600 hover:bg-blue-700"
            >
              View Data
            </Button>
          </Flex>
        </div>
      )}
    </Card>
  );
}

export default FredSeriesExplorer;
