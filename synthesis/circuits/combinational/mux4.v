module mux4(input [3:0] d, input [1:0] s, output y);
  assign y = d[s];
endmodule
