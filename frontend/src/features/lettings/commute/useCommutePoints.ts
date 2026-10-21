import { useQuery } from "@tanstack/react-query";
import { lettings } from "../lib";

/** All commute points (switched on or off) with their journeys. */
export const useCommutePoints = () => useQuery({ queryKey: ["commute-points"], queryFn: lettings.commutePoints });
