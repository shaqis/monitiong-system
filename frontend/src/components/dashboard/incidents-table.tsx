import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { IncidentSummary } from "@/types";

interface IncidentsTableProps {
  incidents: IncidentSummary[];
}

export function IncidentsTable({ incidents }: IncidentsTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Monitor</TableHead>
          <TableHead>Cause</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>State</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {incidents.length === 0 ? (
          <TableRow>
            <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
              No incidents in this range. That is a good sign.
            </TableCell>
          </TableRow>
        ) : (
          incidents.map((incident) => (
            <TableRow key={incident.id}>
              <TableCell className="font-medium">
                <Link href={`/urls/${incident.monitor_id}`} className="hover:underline">
                  {incident.monitor_name}
                </Link>
              </TableCell>
              <TableCell className="max-w-[22rem] truncate text-muted-foreground" title={incident.cause}>
                {incident.cause}
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatDateTime(incident.started_at)}
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatDuration(incident.duration_seconds)}
              </TableCell>
              <TableCell>
                {incident.resolved_at ? (
                  <Badge variant="success">Resolved</Badge>
                ) : (
                  <Badge variant="danger">Ongoing</Badge>
                )}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
