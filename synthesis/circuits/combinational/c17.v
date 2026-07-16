module c17(input N1, N2, N3, N6, N7, output N22, N23);
  wire N10 = ~(N1 & N3); 
  wire N11 = ~(N3 & N6);
  wire N16 = ~(N2 & N11);
  wire N19 = ~(N11 & N7);
  assign N22 = ~(N10 & N16);
  assign N23 = ~(N16 & N19);
endmodule
