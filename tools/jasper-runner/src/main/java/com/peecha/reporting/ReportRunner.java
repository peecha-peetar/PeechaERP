package com.peecha.reporting;

import com.fasterxml.jackson.databind.ObjectMapper;
import net.sf.jasperreports.engine.JasperCompileManager;
import net.sf.jasperreports.engine.JasperExportManager;
import net.sf.jasperreports.engine.JasperFillManager;
import net.sf.jasperreports.engine.JasperPrint;
import net.sf.jasperreports.engine.JasperReport;
import net.sf.jasperreports.engine.data.JsonDataSource;
import net.sf.jasperreports.engine.export.ooxml.JRXlsxExporter;
import net.sf.jasperreports.export.SimpleExporterInput;
import net.sf.jasperreports.export.SimpleOutputStreamExporterOutput;

import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.util.HashMap;
import java.util.Map;

/**
 * ابزارِ خط‌فرمانِ اجرایِ گزارش -- طبقِ معماریِ تصمیم‌گیری‌شده: پایتون
 * (jasper_bridge.py) دیتایِ نهاییِ آماده‌شده توسطِ reports.py/inventory_engine.py
 * را به‌صورتِ JSON می‌دهد و این ابزار فقط چیدمان (طبقِ فایلِ jrxml) و
 * خروجی (PDF/Excel) را انجام می‌دهد -- هیچ کوئریِ SQL یا منطقِ حسابداری‌ای
 * این‌جا وجود ندارد.
 *
 * آرگومان‌ها: <jrxmlPath> <rowsJsonPath> <paramsJsonPath> <outputPath> <format=pdf|xlsx>
 * rowsJsonPath باید یک JSON به‌شکلِ {"rows": [ {...}, {...} ]} باشد.
 * paramsJsonPath یک JSON تخت از رشته‌ها (کلید -> مقدار) برایِ پارامترهایِ گزارش است.
 */
public final class ReportRunner {
    private ReportRunner() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 5) {
            System.err.println("Usage: ReportRunner <jrxmlPath> <rowsJsonPath> <paramsJsonPath> <outputPath> <format=pdf|xlsx>");
            System.exit(2);
        }
        String jrxmlPath = args[0];
        String rowsJsonPath = args[1];
        String paramsJsonPath = args[2];
        String outputPath = args[3];
        String format = args[4].toLowerCase();

        JasperReport jasperReport = JasperCompileManager.compileReport(jrxmlPath);

        Map<String, Object> params = loadParams(paramsJsonPath);

        JsonDataSource dataSource = new JsonDataSource(new FileInputStream(rowsJsonPath), "rows");

        JasperPrint print = JasperFillManager.fillReport(jasperReport, params, dataSource);

        switch (format) {
            case "pdf" -> JasperExportManager.exportReportToPdfFile(print, outputPath);
            case "xlsx" -> {
                JRXlsxExporter exporter = new JRXlsxExporter();
                exporter.setExporterInput(new SimpleExporterInput(print));
                exporter.setExporterOutput(new SimpleOutputStreamExporterOutput(new FileOutputStream(outputPath)));
                exporter.exportReport();
            }
            default -> {
                System.err.println("Unknown format: " + format + " (expected pdf or xlsx)");
                System.exit(2);
            }
        }
    }

    private static Map<String, Object> loadParams(String paramsJsonPath) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        @SuppressWarnings("unchecked")
        Map<String, Object> raw = mapper.readValue(new FileInputStream(paramsJsonPath), Map.class);
        Map<String, Object> params = new HashMap<>();
        for (Map.Entry<String, Object> e : raw.entrySet()) {
            params.put(e.getKey(), e.getValue() == null ? null : String.valueOf(e.getValue()));
        }
        return params;
    }
}
