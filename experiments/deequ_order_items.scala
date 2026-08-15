/*
 * Run Deequ quality analyzers on order_items.csv and write machine-readable
 * baseline results. This is an external comparison, not Buckaroo production
 * code; keep the Spark/Deequ versions with the reported experiment metadata.
 */
import java.io.{File, PrintWriter}

import com.amazon.deequ.VerificationSuite
import com.amazon.deequ.analyzers._
import com.amazon.deequ.analyzers.runners.{AnalyzerContext, AnalysisRunner}
import com.amazon.deequ.checks.{Check, CheckLevel}
import com.amazon.deequ.profiles.ColumnProfilerRunner
import com.amazon.deequ.VerificationResult
import org.apache.spark.sql.functions._

val inputPath = sys.env.getOrElse("DEEQU_INPUT", "/data/order_items.csv")
val outputDir = sys.env.getOrElse("DEEQU_OUTPUT", "/out/deequ_order_items")
new File(outputDir).mkdirs()

val df = spark.read
  .option("header", "true")
  .option("inferSchema", "true")
  .option("multiLine", "false")
  .option("escape", "\"")
  .csv(inputPath)
  .cache()

val columns = df.columns.toSeq
val numericColumns = df.schema.fields
  .filter(field => Set("integer", "long", "double", "float", "decimal", "short").contains(field.dataType.typeName.toLowerCase))
  .map(_.name)
  .toSeq

val profileResult = ColumnProfilerRunner()
  .onData(df)
  .run()

val profileRows = profileResult.profiles.toSeq.map { case (column, profile) =>
  val escapedColumn = column.replace("\"", "\"\"")
  val dataType = profile.dataType.toString.replace("\"", "\"\"")
  val completeness = profile.completeness
  val approxDistinct = profile.approximateNumDistinctValues
  val histogramValues = profile.histogram.map(_.values.size).getOrElse(0)
  s""""$escapedColumn","$dataType",$completeness,$approxDistinct,$histogramValues"""
}

val profileWriter = new PrintWriter(new File(outputDir, "column_profiles.csv"))
profileWriter.println("column,data_type,completeness,approx_distinct,histogram_value_count")
profileRows.sorted.foreach(profileWriter.println)
profileWriter.close()

val baseAnalyzers = columns.flatMap { column =>
  Seq(
    Completeness(column),
    ApproxCountDistinct(column),
    Distinctness(Seq(column))
  )
}

val numericAnalyzers = numericColumns.flatMap { column =>
  Seq(Minimum(column), Maximum(column), Mean(column))
}

val analysisResult = AnalysisRunner
  .onData(df)
  .addAnalyzers(Seq(Size()) ++ baseAnalyzers ++ numericAnalyzers)
  .run()

val metricsDf = AnalyzerContext.successMetricsAsDataFrame(spark, analysisResult)
metricsDf
  .coalesce(1)
  .write
  .mode("overwrite")
  .option("header", "true")
  .csv(s"$outputDir/metrics_csv")

val check = Check(CheckLevel.Error, "order_items sanity checks")
  .hasSize(_ > 0)
  .isComplete("id")
  .isComplete("order_id")
  .isComplete("user_id")
  .isComplete("product_id")
  .isComplete("inventory_item_id")
  .isUnique("id")
  .isUnique("inventory_item_id")
  .isNonNegative("sale_price")
  .isContainedIn("status", Array("Cancelled", "Complete", "Processing", "Returned", "Shipped"))

val verificationResult = VerificationSuite()
  .onData(df)
  .addCheck(check)
  .run()

VerificationResult
  .checkResultsAsDataFrame(spark, verificationResult)
  .coalesce(1)
  .write
  .mode("overwrite")
  .option("header", "true")
  .csv(s"$outputDir/check_results_csv")

val summaryWriter = new PrintWriter(new File(outputDir, "summary.txt"))
summaryWriter.println(s"input=$inputPath")
summaryWriter.println(s"rows=${df.count()}")
summaryWriter.println(s"columns=${columns.length}")
summaryWriter.println(s"column_names=${columns.mkString(",")}")
summaryWriter.println(s"numeric_columns=${numericColumns.mkString(",")}")
summaryWriter.println(s"verification_status=${verificationResult.status}")
summaryWriter.close()

spark.stop()
System.exit(0)
