module seq_bad(input clk, d, output reg q);
  always @(posedge clk) q <= d;
endmodule
