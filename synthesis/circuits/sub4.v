module sub4(input [3:0] a, b, output [3:0] d, output bout);
  assign d    = a - b;
  assign bout = (a < b);
endmodule
