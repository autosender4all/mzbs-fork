"use client";
import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "../Select";
import { useForm } from "react-hook-form";
import { ClassNameAPI as API2 } from "@/api/ClassName/ClassNameAPI";
import { FeeAPI as API3 } from "@/api/Fees/AddFeeAPI"
import { GetFeeModel} from "@/models/fees/Fee";
import { toast } from "sonner";
import { usePrint } from "@/components/print/usePrint";
import { useRole } from "@/context/RoleContext";
import { Printer, ChevronFirst, ChevronLast } from "lucide-react";
import EditFees from "./EditFees";
import DelConfirmMsg from "../DelConfMsg";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Header } from "../dashboard/Header";

const extractArrayData = <T,>(response: unknown): T[] => {
  const payload = (response as { data?: unknown }).data;

  if (Array.isArray(payload)) {
    return payload as T[];
  }

  if (payload && typeof payload === "object") {
    const nested = (payload as { data?: unknown }).data;
    if (Array.isArray(nested)) {
      return nested as T[];
    }
  }

  return [];
};

interface ClassNameResponse {
  class_name_id: number;
  class_name: string;
}

interface FeeData {
  fee_id: number;
  student_name: string;
  father_name: string;
  class_name: string;
  fee_amount: number;
  fee_month: string;
  fee_year: number;
  fee_status: string;
  is_deleted?: boolean;
}

const ViewFees: React.FC = () => {
  const currentDate = new Date();
  const currentYear = currentDate.getFullYear();
  const firstFeeYear = Math.min(2023, currentYear);
  const lastFeeYear = Math.max(2026, currentYear);
  const {
    register,
    handleSubmit,
    setValue: setFormValue,
    formState: { errors },
  } = useForm<GetFeeModel>({
    defaultValues: {
      class_id: 0,
      fee_month: currentDate.toLocaleString("en-US", { month: "long" }),
      fee_year: String(currentYear),
      fee_status: "all",
    },
  });
  const { printRecords } = usePrint();
  const { role, permissions, permissionsLoaded } = useRole();
  const canEditFee = permissionsLoaded && permissions?.fees?.edit === true;
  const [classNameList, setClassNameList] = useState<{ id: number; title: string }[]>([
    { id: 0, title: "All" },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [feesData, setFeesData] = useState<FeeData[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [pageSize] = useState(12);
  const [activeFilters, setActiveFilters] = useState<GetFeeModel | null>(null);
  // Holds the FULL filtered dataset (not just the current page) built right
  // before printing, so the report includes every matching record instead
  // of only the ~12 rows currently visible on screen. Same search-box text
  // filter that's applied on screen is re-applied here too.
  const [printData, setPrintData] = useState<FeeData[]>([]);
  const [isPreparingPrint, setIsPreparingPrint] = useState(false);

  useEffect(() => {
    GetClassName();
  }, []);

  const GetClassName = async () => {                          
    setIsLoading(true);
    try {
      const response = await API2.Get();
      const classes = extractArrayData<ClassNameResponse>(response);
      const allClasses = [{ class_name_id: 0, class_name: "All" }, ...classes];
      setClassNameList(
        allClasses.map((item) => ({
          id: item.class_name_id,
          title: item.class_name,
        }))
      );
    } catch (error) {
      console.error("Error fetching class names:", error);
    } finally {
      setIsLoading(false);
    }
  };

const handleGetFees = async (data: GetFeeModel, page = 1) => {
  try {
    const selectedYear = data.fee_year === "all" ? undefined : data.fee_year;

    if (!data.fee_year) {
      toast.error("Please select a year");
      return;
    }

    setIsLoading(true);
    setCurrentPage(page);
    setActiveFilters(data);

    const response = await API3.Filter({
      class_id: data.class_id && Number(data.class_id) !== 0
        ? Number(data.class_id)
        : undefined,
      fee_month: data.fee_month && data.fee_month !== "all"
        ? data.fee_month
        : undefined,
      fee_year: selectedYear,
      fee_status: data.fee_status && data.fee_status !== "all"
        ? data.fee_status
        : undefined,
      page,
      page_size: pageSize,
    });

    const payload = response?.data;
    const records = Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : [];
    const total = payload?.total ?? records.length;
    const totalPagesFromPayload = payload?.total_pages ?? Math.max(1, Math.ceil(total / pageSize));

    if (records.length === 0) {
      toast.error("No data found");
      setFeesData([]);
      setTotalPages(1);
    } else {
      setFeesData(records as FeeData[]);
      setTotalPages(totalPagesFromPayload);
      toast.success("Fees data fetched successfully");
    }
  } catch (error) {
    console.error("Error fetching fees:", error);
    toast.error("Failed to fetch fees");
  } finally {
    setIsLoading(false);
  }
};

const handlePageChange = (page: number) => {
  if (activeFilters) {
    handleGetFees(activeFilters, page);
  }
};

const handleFeeUpdate = async () => {
  // Re-fetch the fees with current filters
  setFeesData([]);
  toast.success("Fee record updated successfully");
};

const handleDeleteFee = async (feeId: number) => {
  try {
    await API3.Delete(feeId);
    toast.success("Fee record deleted successfully", {
      position: "bottom-center",
      duration: 3000,
    });
    // Remove the deleted fee from the list
    setFeesData(feesData.filter(fee => fee.fee_id !== feeId));
  } catch (error) {
    console.error("Error deleting fee:", error);
    toast.error("Failed to delete fee record");
  }
};

// Fetches every record matching the currently active filters (not just the
// current page) so the printed report is complete. Reuses the same filters
// already applied on screen, plus the same search-box text filter, and
// leaves on-screen pagination completely untouched.
const handlePrintClick = async () => {
  if (!activeFilters) return;
  setIsPreparingPrint(true);
  try {
    const selectedYear = activeFilters.fee_year === "all" ? undefined : activeFilters.fee_year;
    const filterParams = {
      class_id: activeFilters.class_id && Number(activeFilters.class_id) !== 0
        ? Number(activeFilters.class_id)
        : undefined,
      fee_month: activeFilters.fee_month && activeFilters.fee_month !== "all"
        ? activeFilters.fee_month
        : undefined,
      fee_year: selectedYear,
      fee_status: activeFilters.fee_status && activeFilters.fee_status !== "all"
        ? activeFilters.fee_status
        : undefined,
    };
    
    // Fetch first page to get total_pages
    const firstPageResponse = await API3.Filter({
      ...filterParams,
      page: 1,
      page_size: 50,
    });
    const payload = firstPageResponse?.data;
    const totalPages = payload?.total_pages || 1;
    
    // Collect all records from all pages
    let allRecords: FeeData[] = [];
    for (let page = 1; page <= totalPages; page++) {
      const response = await API3.Filter({
        ...filterParams,
        page,
        page_size: 50,
      });
      const pagePayload = response?.data;
      const records = Array.isArray(pagePayload?.data) ? pagePayload.data : Array.isArray(pagePayload) ? pagePayload : [];
      const searchLower = searchQuery.toLowerCase();
      const filtered = (records as FeeData[]).filter((fee) =>
        fee.student_name.toLowerCase().includes(searchLower) ||
        fee.father_name.toLowerCase().includes(searchLower) ||
        fee.class_name.toLowerCase().includes(searchLower) ||
        fee.fee_month.toLowerCase().includes(searchLower) ||
        fee.fee_status.toLowerCase().includes(searchLower)
      );
      allRecords = [...allRecords, ...filtered];
    }
    setPrintData(allRecords);
  } catch (error) {
    console.error("Failed to prepare print data", error);
    toast.error("Failed to prepare print data");
    setIsPreparingPrint(false);
  }
};

// Once the full dataset lands, print it, then clear it out again.
useEffect(() => {
  if (printData.length === 0) return;
  const meta = `Total records: ${printData.length} · Printed: ${new Date().toLocaleDateString()}`;
  printRecords('fees-print-area-full', 'Fees Report', meta);
  setPrintData([]);
  setIsPreparingPrint(false);
}, [printData, printRecords]);

// Filter fees based on search query
const filteredFeesData = feesData.filter((fee) => {
  const searchLower = searchQuery.toLowerCase();
  return (
    fee.student_name.toLowerCase().includes(searchLower) ||
    fee.father_name.toLowerCase().includes(searchLower) ||
    fee.class_name.toLowerCase().includes(searchLower) ||
    fee.fee_month.toLowerCase().includes(searchLower) ||
    fee.fee_status.toLowerCase().includes(searchLower)
  );
});

  return (
    <div className="container mx-auto px-2 sm:px-4">
      <Header value="View Fees" />
      <div className="mt-3 rounded-[24px] border border-border/80 bg-card/80 shadow-[0_16px_40px_-22px_rgba(15,23,42,0.35)] backdrop-blur-xl dark:border-border dark:bg-background/70">
        <form
          onSubmit={handleSubmit((data) => handleGetFees(data, 1))}
          className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2 sm:gap-4 sm:p-4 lg:grid-cols-5 lg:items-end"
        >
          <div className="col-span-1">
            <label className="text-sm text-foreground dark:text-foreground font-bold">
              Class Name
            </label>
            <Select
              label=""
              options={classNameList}
              {...register("class_id")}
              className="w-full"
            />
          </div>
          <div className="col-span-1">
            <label className="text-sm text-foreground dark:text-foreground font-bold">
              Fee Month
            </label>
            <Select
              label=""
              options={[
                { id: "all", title: "All" },
                { id: "January", title: "January" },
                { id: "February", title: "February" },
                { id: "March", title: "March" },
                { id: "April", title: "April" },
                { id: "May", title: "May" },
                { id: "June", title: "June" },
                { id: "July", title: "July" },
                { id: "August", title: "August" },
                { id: "September", title: "September" },
                { id: "October", title: "October" },
                { id: "November", title: "November" },
                { id: "December", title: "December" },
              ]}
              {...register("fee_month")}
              className="w-full"
            />
          </div>
          <div className="col-span-1">
            <label className="text-sm text-foreground dark:text-foreground font-bold">
              Fee Year
            </label>
            <Select
              label=""
              options={[
                { id: "all", title: "All" },
                ...Array.from(
                  { length: lastFeeYear - firstFeeYear + 1 },
                  (_, index) => {
                    const year = firstFeeYear + index;
                    return { id: String(year), title: String(year) };
                  }
                ),
              ]}
              {...register("fee_year")}
              className="w-full"
            />
          </div>
          <div className="col-span-1">
            <label className="text-sm text-foreground dark:text-foreground font-bold">
              Fee Status
            </label>
            <Select
              label=""
              options={[
                { id: "all", title: "All" },
                { id: "Paid", title: "Paid" },
                { id: "Unpaid", title: "Unpaid" },
              ]}
              {...register("fee_status")}
              className="w-full"
            />
          </div>
          <Button className="w-full rounded-xl lg:col-span-1" type="submit">
            Get
          </Button>
        </form>

        {feesData.length > 0 && (
          <div className="p-2 sm:p-4">
            <div className="mb-4 flex items-center justify-between gap-3 no-print">
              <h3 className="text-lg font-semibold text-foreground dark:text-foreground">Fees Data</h3>
              <button
                onClick={handlePrintClick}
                disabled={isPreparingPrint}
                className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary to-primary px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:from-primary/90 hover:to-primary/90"
              >
                <Printer size={16} />
                {isPreparingPrint ? 'Preparing...' : 'Print'}
              </button>
            </div>

            <div className="mb-4 flex flex-wrap items-center justify-between gap-2 no-print">
              <p className="text-sm text-muted-foreground dark:text-muted-foreground">
                Page {currentPage} of {totalPages}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(1)}
                  disabled={currentPage === 1 || isLoading}
                  className="px-2 sm:px-3"
                  aria-label="First page"
                >
                  <ChevronFirst className="h-4 w-4" />
                  <span className="hidden sm:inline ml-1">First</span>
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1 || isLoading}
                  className="px-2 sm:px-3"
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages || isLoading}
                  className="px-2 sm:px-3"
                >
                  Next
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(totalPages)}
                  disabled={currentPage === totalPages || isLoading}
                  className="px-2 sm:px-3"
                  aria-label="Last page"
                >
                  <span className="hidden sm:inline mr-1">Last</span>
                  <ChevronLast className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* Search Bar */}
            <div className="mb-4 no-print">
              <Input
                type="text"
                placeholder="Search by student name, father name, class, month, or status..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-xl border-border px-4 py-2.5 shadow-sm focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-border dark:focus:border-primary dark:focus:ring-primary/20"
              />
              {filteredFeesData.length !== feesData.length && (
                <p className="mt-2 text-sm text-muted-foreground dark:text-muted-foreground">
                  Showing {filteredFeesData.length} of {feesData.length} records
                </p>
              )}
            </div>

            <div id="fees-print-area" className="overflow-x-auto rounded-[20px] border border-border/80 bg-card/80 dark:border-border dark:bg-background/70">
              <Table className="min-w-[760px] w-full">
                <TableHeader className="bg-muted/90 dark:bg-card/80">
                  <TableRow>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em]">Student Name</TableHead>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em]">Father Name</TableHead>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em]">Class</TableHead>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em]">Amount</TableHead>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em]">Month</TableHead>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em]">Year</TableHead>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em]">Status</TableHead>
                    <TableHead className="w-1/8 px-3 py-3 text-xs font-semibold uppercase tracking-[0.16em] no-print">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredFeesData.length > 0 ? (
                    filteredFeesData.map((fee) => (
                      <TableRow 
                        key={fee.fee_id} 
                        className={fee.is_deleted ? "bg-muted/70 opacity-60 dark:bg-card/70" : "hover:bg-muted/70 dark:hover:bg-card/70"}
                      >
                        <TableCell className={fee.is_deleted ? "px-3 py-3 text-muted-foreground dark:text-muted-foreground" : "px-3 py-3 text-foreground dark:text-foreground"}>
                          {fee.student_name}
                        </TableCell>
                        <TableCell className={fee.is_deleted ? "px-3 py-3 text-muted-foreground dark:text-muted-foreground" : "px-3 py-3 text-foreground dark:text-foreground"}>
                          {fee.father_name}
                        </TableCell>
                        <TableCell className={fee.is_deleted ? "px-3 py-3 text-muted-foreground dark:text-muted-foreground" : "px-3 py-3 text-foreground dark:text-foreground"}>
                          {fee.class_name}
                        </TableCell>
                        <TableCell className={fee.is_deleted ? "px-3 py-3 text-muted-foreground dark:text-muted-foreground" : "px-3 py-3 text-foreground dark:text-foreground"}>
                          {fee.fee_amount}
                        </TableCell>
                        <TableCell className={fee.is_deleted ? "px-3 py-3 text-muted-foreground dark:text-muted-foreground" : "px-3 py-3 text-foreground dark:text-foreground"}>
                          {fee.fee_month}
                        </TableCell>
                        <TableCell className={fee.is_deleted ? "px-3 py-3 text-muted-foreground dark:text-muted-foreground" : "px-3 py-3 text-foreground dark:text-foreground"}>
                          {fee.fee_year}
                        </TableCell>
                        <TableCell>
                          <span className={`px-2 py-1 rounded-full text-xs ${
                            fee.fee_status === "Paid" 
                              ? "bg-primary/10 text-green-800" 
                              : "bg-red-100 text-red-800"
                          }`}>
                            {fee.fee_status}
                          </span>
                        </TableCell>
                        <TableCell className="px-3 py-3 no-print">
                          {(canEditFee || (role === "ADMIN" && fee.fee_id)) && (
                            <div className="flex items-center gap-2 justify-center">
                              {canEditFee && (
                                <EditFees
                                  feeId={fee.fee_id}
                                  studentName={fee.student_name}
                                  fatherName={fee.father_name}
                                  className={fee.class_name}
                                  feeStatus={fee.fee_status}
                                  feeAmount={fee.fee_amount}
                                  feeMonth={fee.fee_month}
                                  feeYear={fee.fee_year}
                                  onUpdate={handleFeeUpdate}
                                />
                              )}
                              {role === "ADMIN" && fee.fee_id && (
                                <DelConfirmMsg
                                  rowId={fee.fee_id}
                                  OnDelete={(confirmed) => {
                                    if (confirmed) {
                                      handleDeleteFee(fee.fee_id);
                                    }
                                  }}
                                  title="Delete Fee Record?"
                                  text={`Are you sure you want to delete the fee record for ${fee.student_name}? This action cannot be undone.`}
                                />
                              )}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={8} className="py-6 text-center text-sm text-muted-foreground dark:text-muted-foreground">
                        No records found matching your search.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <div id="fees-print-area-full" style={{ display: "none" }}>
              <Table className="min-w-[760px] w-full">
                <TableHeader>
                  <TableRow>
                    <TableHead>Student Name</TableHead>
                    <TableHead>Father Name</TableHead>
                    <TableHead>Class</TableHead>
                    <TableHead>Amount</TableHead>
                    <TableHead>Month</TableHead>
                    <TableHead>Year</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {printData.map((fee) => (
                    <TableRow key={fee.fee_id}>
                      <TableCell>{fee.student_name}</TableCell>
                      <TableCell>{fee.father_name}</TableCell>
                      <TableCell>{fee.class_name}</TableCell>
                      <TableCell>{fee.fee_amount}</TableCell>
                      <TableCell>{fee.fee_month}</TableCell>
                      <TableCell>{fee.fee_year}</TableCell>
                      <TableCell>{fee.fee_status}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ViewFees;
